"""Provider adapter contract.

Every AI provider (Groq, Gemini, OpenRouter, Pollinations, ...) implements
:class:`ProviderAdapter`. This is the single interface the routing engine,
the discovery pipeline, and every adapter build against — adding a new
provider later means writing one new file that satisfies this Protocol,
nothing else changes.

Deliberately decoupled from the DB layer: every type here is a plain
Pydantic model, not a SQLAlchemy row, so adapters never need a DB session.
Callers translate between these DTOs and ORM rows at the boundary.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class MessageContentPart(BaseModel):
    """One part of a multimodal message (text or image) for vision models."""

    model_config = ConfigDict(frozen=True)

    type: Literal["text", "image_url"]
    text: str | None = None
    image_url: str | None = None


class Message(BaseModel):
    """A single chat message, OpenAI-shaped."""

    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str | list[MessageContentPart]


class DiscoveredModel(BaseModel):
    """One model returned by an adapter's ``discover_models``."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    display_name: str
    supports_vision: bool = False
    context_length: int | None = None
    raw_metadata: dict[str, Any] = {}


class BenchmarkResult(BaseModel):
    """Result of timing one short fixed prompt against a model."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    success: bool
    latency_ms: float | None = None
    speed_rating: int | None = None  # 1-5, bucketed from latency_ms; None if failed
    error: str | None = None


class ChatChunk(BaseModel):
    """One streamed chunk of a chat completion."""

    model_config = ConfigDict(frozen=True)

    delta: str
    finish_reason: Literal["stop", "length", "content_filter"] | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None


class ImageResult(BaseModel):
    """Result of an image generation call."""

    model_config = ConfigDict(frozen=True)

    url: str | None = None
    b64_data: str | None = None
    mime_type: str = "image/png"


class HealthStatus(BaseModel):
    """Result of a lightweight liveness probe against a provider."""

    model_config = ConfigDict(frozen=True)

    healthy: bool
    checked_at: datetime
    latency_ms: float | None = None
    detail: str | None = None


class QuotaStatus(BaseModel):
    """Traffic-light-ready quota summary for a provider."""

    model_config = ConfigDict(frozen=True)

    exhausted: bool
    remaining: int | None = None  # None = unknown/unbounded
    limit: int | None = None
    reset_at: datetime | None = None


class QuotaUsage(BaseModel):
    """Read-only snapshot of a QuotaUsage row, passed into ``remaining_quota``.

    Mirrors the DB row's shape without requiring a DB session in adapters.
    """

    model_config = ConfigDict(frozen=True)

    provider_name: str
    date: date
    request_count: int
    daily_limit: int | None = None


@runtime_checkable
class ProviderAdapter(Protocol):
    """Structural contract every provider adapter must satisfy."""

    name: str
    auth_type: Literal["api_key", "none", "local"]

    async def validate_key(self, api_key: str | None) -> bool:
        """Lightweight check that ``api_key`` is accepted by the provider.

        Used by the onboarding pipeline's first step; should be cheap
        (a list-models call or a 1-token completion), not a full discovery.
        """
        ...

    async def discover_models(self, api_key: str | None) -> list[DiscoveredModel]:
        """Return the live list of models available for this key.

        Calls the provider's own model-list endpoint where one exists;
        falls back to a static known list in the adapter otherwise.
        """
        ...

    async def benchmark(self, model_id: str, api_key: str | None) -> BenchmarkResult:
        """Time one short fixed prompt (e.g. "Reply with the word OK.")."""
        ...

    async def chat(
        self, messages: list[Message], model_id: str, **kwargs: Any
    ) -> AsyncIterator[ChatChunk]:
        """Stream a chat completion for ``model_id``."""
        ...

    async def generate_image(self, prompt: str, **kwargs: Any) -> ImageResult:
        """Generate an image from ``prompt``."""
        ...

    async def health_check(self) -> HealthStatus:
        """Cheap liveness probe, independent of any particular model."""
        ...

    def remaining_quota(self, usage_row: QuotaUsage) -> QuotaStatus:
        """Derive a traffic-light-ready quota status from a usage snapshot.

        Synchronous and pure: no I/O, just arithmetic against the provider's
        known rate limits.
        """
        ...
