from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx

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


class OpenRouterAdapter(ProviderAdapter):
    """Adapter for the OpenRouter API provider."""

    name: str = "openrouter"
    auth_type: Literal["api_key", "none", "local"] = "api_key"

    def __init__(self, base_url: str = "https://openrouter.ai/api/v1") -> None:
        self._base_url = base_url.rstrip("/")

    async def validate_key(self, api_key: str | None) -> bool:
        """Lightweight check that ``api_key`` is accepted by the provider."""
        if not api_key:
            return False
        try:
            async with httpx.AsyncClient() as client:
                headers = {"Authorization": f"Bearer {api_key}"}
                response = await client.get(f"{self._base_url}/key", headers=headers, timeout=5.0)
                return response.status_code == 200
        except Exception:
            return False

    async def discover_models(self, api_key: str | None) -> list[DiscoveredModel]:
        """Return the live list of models available for this key.

        Filters for free models (where price is 0).
        """
        if not api_key:
            return []
        try:
            async with httpx.AsyncClient() as client:
                headers = {"Authorization": f"Bearer {api_key}"}
                response = await client.get(
                    f"{self._base_url}/models", headers=headers, timeout=10.0
                )
                if response.status_code != 200:
                    return []

                data = response.json()
                models_list = data.get("data", [])

                discovered = []
                for item in models_list:
                    model_id = item.get("id")
                    if not model_id:
                        continue

                    # Filter for free models (where prompt pricing is 0)
                    pricing = item.get("pricing", {})
                    try:
                        prompt_price = float(pricing.get("prompt", 0))
                    except (ValueError, TypeError):
                        prompt_price = 0.0

                    if prompt_price != 0.0:
                        continue

                    display_name = item.get("name") or model_id

                    # Detect vision support, ensuring we don't match false positives like "novision"
                    architecture = item.get("architecture", {})
                    input_modalities = architecture.get("input_modalities", [])
                    supports_vision = (
                        "vision" in model_id.lower() and "novision" not in model_id.lower()
                    ) or "image" in input_modalities

                    context_length = item.get("context_length")

                    discovered.append(
                        DiscoveredModel(
                            model_id=model_id,
                            display_name=display_name,
                            supports_vision=supports_vision,
                            context_length=context_length,
                            raw_metadata=item,
                        )
                    )
                return discovered
        except Exception:
            return []

    async def benchmark(self, model_id: str, api_key: str | None) -> BenchmarkResult:
        """Time one short fixed prompt (e.g. "Reply with the word OK.")."""
        if not api_key:
            return BenchmarkResult(
                model_id=model_id,
                success=False,
                error="API key is missing.",
            )

        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/omni-ai/gateway",
                    "X-Title": "Omni AI Gateway",
                }
                payload = {
                    "model": model_id,
                    "messages": [{"role": "user", "content": "Reply with the word OK."}],
                    "max_tokens": 5,
                }
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=10.0,
                )

                latency_ms = (time.perf_counter() - start_time) * 1000

                if response.status_code != 200:
                    return BenchmarkResult(
                        model_id=model_id,
                        success=False,
                        latency_ms=latency_ms,
                        error=(
                            f"OpenRouter API benchmark failed "
                            f"(status {response.status_code}): {response.text}"
                        ),
                    )

                speed_rating = self._calculate_speed_rating(latency_ms)
                return BenchmarkResult(
                    model_id=model_id,
                    success=True,
                    latency_ms=latency_ms,
                    speed_rating=speed_rating,
                )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return BenchmarkResult(
                model_id=model_id,
                success=False,
                latency_ms=latency_ms,
                error=f"Benchmark error: {exc}",
            )

    async def chat(
        self, messages: list[Message], model_id: str, **kwargs: Any
    ) -> AsyncIterator[ChatChunk]:
        """Stream a chat completion for ``model_id``."""
        api_key = kwargs.pop("api_key", None)
        if not api_key:
            raise ValueError("API key is required for OpenRouter chat completions.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/omni-ai/gateway",
            "X-Title": "Omni AI Gateway",
        }

        # Normalize message content formats
        formatted_messages: list[dict[str, Any]] = []
        for m in messages:
            if isinstance(m.content, str):
                formatted_messages.append({"role": m.role, "content": m.content})
            else:
                parts: list[dict[str, Any]] = []
                for part in m.content:
                    if part.type == "text":
                        parts.append({"type": "text", "text": part.text})
                    elif part.type == "image_url":
                        parts.append({"type": "image_url", "image_url": {"url": part.image_url}})
                formatted_messages.append({"role": m.role, "content": parts})

        payload: dict[str, Any] = {
            "model": model_id,
            "messages": formatted_messages,
            "stream": True,
        }
        # Merge other completions kwargs
        payload.update(kwargs)

        async def _stream() -> AsyncIterator[ChatChunk]:
            async with httpx.AsyncClient() as client, client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=30.0,
            ) as response:
                if response.status_code != 200:
                    error_content = await response.aread()
                    raise httpx.HTTPStatusError(
                        message=(
                            f"OpenRouter API error (status {response.status_code}): "
                            f"{error_content.decode()}"
                        ),
                        request=response.request,
                        response=response,
                    )

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[len("data: ") :]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            choice = chunk["choices"][0]
                            delta = choice.get("delta", {})
                            content = delta.get("content", "")
                            finish_reason = choice.get("finish_reason", None)

                            usage = chunk.get("usage")
                            tokens_in = None
                            tokens_out = None
                            if usage:
                                tokens_in = usage.get("prompt_tokens")
                                tokens_out = usage.get("completion_tokens")

                            yield ChatChunk(
                                delta=content,
                                finish_reason=finish_reason,
                                tokens_in=tokens_in,
                                tokens_out=tokens_out,
                            )
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

        return _stream()

    async def generate_image(self, prompt: str, **kwargs: Any) -> ImageResult:
        """Generate an image from ``prompt``."""
        raise NotImplementedError("OpenRouter does not support image generation.")

    async def health_check(self) -> HealthStatus:
        """Cheap liveness probe, independent of any particular model."""
        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self._base_url}/models", timeout=5.0)
                latency_ms = (time.perf_counter() - start_time) * 1000
                if response.status_code >= 500:
                    return HealthStatus(
                        healthy=False,
                        checked_at=datetime.now(UTC),
                        latency_ms=latency_ms,
                        detail=f"OpenRouter API returned server error: {response.status_code}",
                    )
                return HealthStatus(
                    healthy=True,
                    checked_at=datetime.now(UTC),
                    latency_ms=latency_ms,
                    detail=f"OpenRouter API reachable. Status: {response.status_code}",
                )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return HealthStatus(
                healthy=False,
                checked_at=datetime.now(UTC),
                latency_ms=latency_ms,
                detail=f"OpenRouter API unreachable: {exc}",
            )

    def remaining_quota(self, usage_row: QuotaUsage) -> QuotaStatus:
        """Derive a traffic-light-ready quota status from a usage snapshot."""
        limit = usage_row.daily_limit if usage_row.daily_limit is not None else 50
        remaining = max(0, limit - usage_row.request_count)
        exhausted = remaining <= 0

        # Midnight of the next day relative to usage_row.date
        reset_date = usage_row.date + timedelta(days=1)
        reset_at = datetime.combine(reset_date, datetime.min.time(), tzinfo=UTC)

        return QuotaStatus(
            exhausted=exhausted,
            remaining=remaining,
            limit=limit,
            reset_at=reset_at,
        )

    def _calculate_speed_rating(self, latency_ms: float) -> int:
        if latency_ms <= 300:
            return 5
        elif latency_ms <= 600:
            return 4
        elif latency_ms <= 1200:
            return 3
        elif latency_ms <= 2400:
            return 2
        else:
            return 1
