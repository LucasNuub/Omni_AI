"""A controllable fake adapter for exercising routing/streaming without network calls.

Real adapters are tested against mocked HTTP calls in ``tests/providers/``.
Here, the adapter itself is faked so API-layer tests (routing, fallback,
SSE framing, error normalization) don't depend on any one provider's wire
format.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, cast

from app.providers.base import (
    BenchmarkResult,
    ChatChunk,
    DiscoveredModel,
    HealthStatus,
    ImageResult,
    Message,
    ProviderAdapter,
    QuotaStatus,
    QuotaUsage,
)


@dataclass
class FakeAdapter:
    name: str
    auth_type: Literal["api_key", "none", "local"] = "none"
    chat_chunks: list[ChatChunk] = field(
        default_factory=lambda: [ChatChunk(delta="Hello", finish_reason="stop")]
    )
    fail_immediately: bool = False
    fail_after: int | None = None
    healthy: bool = True
    quota_remaining: int | None = 100
    quota_limit: int | None = 100

    # Discovery pipeline controls (see discovery/scanner.py).
    validate_key_result: bool = True
    validate_key_raises: bool = False
    discovered_models: list[DiscoveredModel] = field(default_factory=list)
    discover_raises: bool = False
    benchmark_results: dict[str, BenchmarkResult] = field(default_factory=dict)
    benchmark_raises_for: frozenset[str] = frozenset()

    async def validate_key(self, api_key: str | None) -> bool:
        if self.validate_key_raises:
            raise RuntimeError(f"{self.name} validate_key network error")
        return self.validate_key_result

    async def discover_models(self, api_key: str | None) -> list[DiscoveredModel]:
        if self.discover_raises:
            raise RuntimeError(f"{self.name} discover_models network error")
        return self.discovered_models

    async def benchmark(self, model_id: str, api_key: str | None) -> BenchmarkResult:
        if model_id in self.benchmark_raises_for:
            raise RuntimeError(f"{self.name} benchmark timeout for {model_id}")
        if model_id in self.benchmark_results:
            return self.benchmark_results[model_id]
        return BenchmarkResult(model_id=model_id, success=True, latency_ms=1.0, speed_rating=5)

    async def chat(
        self, messages: list[Message], model_id: str, **kwargs: Any
    ) -> AsyncIterator[ChatChunk]:
        if self.fail_immediately:
            raise RuntimeError(f"{self.name} is unavailable")
        for i, chunk in enumerate(self.chat_chunks):
            if self.fail_after is not None and i == self.fail_after:
                raise RuntimeError(f"{self.name} failed mid-stream")
            yield chunk

    async def generate_image(self, prompt: str, **kwargs: Any) -> ImageResult:
        raise NotImplementedError

    async def health_check(self) -> HealthStatus:
        return HealthStatus(healthy=self.healthy, checked_at=datetime.now(UTC))

    def remaining_quota(self, usage_row: QuotaUsage) -> QuotaStatus:
        return QuotaStatus(
            exhausted=self.quota_remaining == 0,
            remaining=self.quota_remaining,
            limit=self.quota_limit,
            reset_at=None,
        )


def as_adapter(fake: FakeAdapter) -> ProviderAdapter:
    """Cast a FakeAdapter for callers typed against ProviderAdapter.

    FakeAdapter's real (yield-based) ``chat`` doesn't structurally match the
    Protocol's ``async def chat(...) -> AsyncIterator[ChatChunk]`` under
    mypy's stricter reading (coroutine-returning-an-iterator vs. async
    generator) — the same mismatch worked around in api/chat.py and
    providers/registry.py. This reflects FakeAdapter's actual runtime
    behavior, not a real type error.
    """
    return cast(ProviderAdapter, fake)
