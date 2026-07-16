from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
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


def latency_to_rating(latency_ms: float) -> int:
    if latency_ms < 500:
        return 5
    elif latency_ms < 1000:
        return 4
    elif latency_ms < 2000:
        return 3
    elif latency_ms < 4000:
        return 2
    else:
        return 1


class GeminiAdapter(ProviderAdapter):
    """Google Gemini AI Studio provider adapter."""

    name: str = "gemini"
    auth_type: Literal["api_key"] = "api_key"

    def __init__(
        self, base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    ) -> None:
        self.base_url = base_url

    async def validate_key(self, api_key: str | None) -> bool:
        """Lightweight check that ``api_key`` is accepted by the provider."""
        if not api_key:
            return False

        headers = {
            "Authorization": f"Bearer {api_key}",
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/v1/models",
                    headers=headers,
                    timeout=5.0,
                )
                return response.status_code == 200
        except Exception:
            return False

    async def discover_models(self, api_key: str | None) -> list[DiscoveredModel]:
        """Return the live list of models available for this key."""
        if not api_key:
            return []

        headers = {
            "Authorization": f"Bearer {api_key}",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/v1/models",
                headers=headers,
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

        models_data = data.get("data", [])
        discovered: list[DiscoveredModel] = []

        context_lengths = {
            "gemini-1.5-pro": 2097152,
            "gemini-1.5-flash": 1048576,
            "gemini-2.0-flash": 1048576,
            "gemini-2.0-flash-exp": 1048576,
            "gemini-2.5-flash": 1048576,
            "gemini-2.5-pro": 2097152,
        }

        for model in models_data:
            model_id = model.get("id")
            if not model_id:
                continue

            # supports_vision checks
            supports_vision = any(
                term in model_id.lower()
                for term in ("gemini-1.5", "vision", "gemini-2", "gemini-3.5")
            )

            # Context length guessing
            context_len = None
            for key, val in context_lengths.items():
                if key in model_id.lower():
                    context_len = val
                    break

            if context_len is None:
                if "pro" in model_id.lower():
                    context_len = 2097152
                elif "flash" in model_id.lower():
                    context_len = 1048576
                else:
                    context_len = 128000  # Default context length

            # Clean up display name or use ID
            display_name = model.get("display_name", model_id)

            discovered.append(
                DiscoveredModel(
                    model_id=model_id,
                    display_name=display_name,
                    supports_vision=supports_vision,
                    context_length=context_len,
                    raw_metadata=model,
                )
            )

        return discovered

    async def benchmark(self, model_id: str, api_key: str | None) -> BenchmarkResult:
        """Time one short fixed prompt against the model."""
        if not api_key:
            return BenchmarkResult(
                model_id=model_id,
                success=False,
                error="API key is missing.",
            )

        import time

        start_time = time.perf_counter()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply with the word OK."}],
            "max_tokens": 5,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=10.0,
                )
                response.raise_for_status()

            latency_ms = (time.perf_counter() - start_time) * 1000.0
            rating = latency_to_rating(latency_ms)
            return BenchmarkResult(
                model_id=model_id,
                success=True,
                latency_ms=latency_ms,
                speed_rating=rating,
            )
        except Exception as e:
            return BenchmarkResult(
                model_id=model_id,
                success=False,
                error=str(e),
            )

    async def chat(  # type: ignore[override, misc]
        self, messages: list[Message], model_id: str, **kwargs: Any
    ) -> AsyncIterator[ChatChunk]:
        """Stream a chat completion for ``model_id``."""
        api_key = kwargs.pop("api_key", None)
        if not api_key:
            raise ValueError("Gemini API key is required.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        formatted_messages: list[dict[str, Any]] = []
        for msg in messages:
            if isinstance(msg.content, list):
                content_list = []
                for part in msg.content:
                    part_dict: dict[str, Any] = {"type": part.type}
                    if part.text is not None:
                        part_dict["text"] = part.text
                    if part.image_url is not None:
                        part_dict["image_url"] = {"url": part.image_url}
                    content_list.append(part_dict)
                formatted_messages.append({"role": msg.role, "content": content_list})
            else:
                formatted_messages.append({"role": msg.role, "content": msg.content})

        payload = {
            "model": model_id,
            "messages": formatted_messages,
            "stream": True,
            **kwargs,
        }

        async with httpx.AsyncClient() as client, client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30.0,
        ) as response:
            if response.status_code != 200:
                await response.aread()
                response.raise_for_status()

            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                if line.startswith("data: "):
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk_data = json.loads(data)
                        choices = chunk_data.get("choices", [])
                        if not choices:
                            continue

                        choice = choices[0]
                        delta = choice.get("delta", {})
                        content = delta.get("content", "")
                        raw_finish_reason = choice.get("finish_reason")

                        # Sanitize finish_reason to match base.py spec
                        if raw_finish_reason not in ("stop", "length", "content_filter"):
                            finish_reason = None
                        else:
                            finish_reason = raw_finish_reason

                        usage = chunk_data.get("usage")
                        tokens_in = usage.get("prompt_tokens") if usage else None
                        tokens_out = usage.get("completion_tokens") if usage else None

                        yield ChatChunk(
                            delta=content,
                            finish_reason=finish_reason,
                            tokens_in=tokens_in,
                            tokens_out=tokens_out,
                        )
                    except json.JSONDecodeError:
                        continue

    async def generate_image(self, prompt: str, **kwargs: Any) -> ImageResult:
        """Generate an image from ``prompt``."""
        raise NotImplementedError("Image generation is not supported by Gemini.")

    async def health_check(self) -> HealthStatus:
        """Cheap liveness probe, independent of any particular model."""
        import time

        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.base_url, timeout=5.0)
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return HealthStatus(
                healthy=True,
                checked_at=datetime.now(UTC),
                latency_ms=latency_ms,
                detail=f"Reachable, status code: {response.status_code}",
            )
        except Exception as e:
            return HealthStatus(
                healthy=False,
                checked_at=datetime.now(UTC),
                detail=str(e),
            )

    def remaining_quota(self, usage_row: QuotaUsage) -> QuotaStatus:
        """Derive a traffic-light-ready quota status from a usage snapshot."""
        limit = usage_row.daily_limit if usage_row.daily_limit is not None else 1500
        remaining = max(0, limit - usage_row.request_count)
        exhausted = remaining <= 0

        # Resets at midnight UTC of the next day
        reset_at = datetime.combine(
            usage_row.date + timedelta(days=1),
            time.min,
            tzinfo=UTC,
        )

        return QuotaStatus(
            exhausted=exhausted,
            remaining=remaining,
            limit=limit,
            reset_at=reset_at,
        )
