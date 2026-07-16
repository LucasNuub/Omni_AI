from __future__ import annotations

import base64
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote

import httpx

from app.providers.base import (
    BenchmarkResult,
    ChatChunk,
    DiscoveredModel,
    HealthStatus,
    ImageResult,
    Message,
    QuotaStatus,
    QuotaUsage,
)

STATIC_MODELS = [
    {"id": "openai", "context_length": 400000},
    {"id": "openai-fast", "context_length": 400000},
    {"id": "mistral", "context_length": 262144},
    {"id": "llama", "context_length": 131072},
    {"id": "qwen-coder", "context_length": 262144},
    {"id": "gemma", "context_length": 262144},
]


class PollinationsAdapter:
    """Provider adapter for Pollinations.ai."""

    name: str = "pollinations"
    auth_type: Literal["api_key", "none", "local"] = "none"

    async def validate_key(self, api_key: str | None) -> bool:
        """Lightweight check that api_key is accepted.

        No key is needed for Pollinations, so always returns True.
        """
        return True

    async def discover_models(self, api_key: str | None) -> list[DiscoveredModel]:
        """Return the live list of models available from Pollinations.ai.

        Falls back to a static list if the endpoint fails.
        """
        headers = {"Authorization": ""}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://gen.pollinations.ai/v1/models",
                    headers=headers,
                    timeout=10.0,
                )
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("data", []) if isinstance(data, dict) else data
                    if isinstance(items, list) and items:
                        models = []
                        for item in items:
                            model_id = item.get("id")
                            if not model_id:
                                continue
                            context_length = item.get("context_length")
                            input_modalities = item.get("input_modalities", [])
                            supports_vision = (
                                "image" in input_modalities
                                or "vision" in model_id.lower()
                            )
                            models.append(
                                DiscoveredModel(
                                    model_id=model_id,
                                    display_name=model_id,
                                    supports_vision=supports_vision,
                                    context_length=context_length,
                                    raw_metadata=item,
                                )
                            )
                        return models
        except Exception:
            # Fall back to static models list on failure
            pass

        return [
            DiscoveredModel(
                model_id=m["id"],
                display_name=m["id"],
                supports_vision=False,
                context_length=m["context_length"],
                raw_metadata={},
            )
            for m in STATIC_MODELS
        ]

    async def chat(
        self, messages: list[Message], model_id: str, **kwargs: Any
    ) -> AsyncIterator[ChatChunk]:
        """Stream a chat completion for model_id."""
        headers = {"Authorization": ""}
        formatted_messages = [m.model_dump(exclude_none=True) for m in messages]
        payload = {
            "model": model_id,
            "messages": formatted_messages,
            "stream": True,
        }
        for k, v in kwargs.items():
            if k not in ("model", "messages", "stream"):
                payload[k] = v

        async with (
            httpx.AsyncClient() as client,
            client.stream(
                "POST",
                "https://gen.pollinations.ai/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=60.0,
            ) as response,
        ):
            if response.status_code >= 400:
                error_text = await response.aread()
                error_msg = error_text.decode(errors="ignore")
                raise httpx.HTTPStatusError(
                    f"Error response {response.status_code}: {error_msg}",
                    request=response.request,
                    response=response,
                )

            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[len("data: ") :].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_data = json.loads(data_str)
                        choices = chunk_data.get("choices", [])
                        delta_text = ""
                        finish_reason = None
                        if choices:
                            choice = choices[0]
                            delta_text = choice.get("delta", {}).get("content", "") or ""
                            finish_reason = choice.get("finish_reason")

                        usage = chunk_data.get("usage")
                        tokens_in = usage.get("prompt_tokens") if usage else None
                        tokens_out = usage.get("completion_tokens") if usage else None

                        has_tokens = tokens_in is not None or tokens_out is not None
                        if delta_text or finish_reason or has_tokens:
                            yield ChatChunk(
                                delta=delta_text,
                                finish_reason=finish_reason,
                                tokens_in=tokens_in,
                                tokens_out=tokens_out,
                            )
                    except Exception:
                        continue

    async def benchmark(self, model_id: str, api_key: str | None) -> BenchmarkResult:
        """Time one short fixed prompt."""
        start_time = time.perf_counter()
        try:
            messages = [Message(role="user", content="Reply with the word OK.")]
            chunks = []
            async for chunk in self.chat(messages, model_id):
                chunks.append(chunk)

            latency_ms = (time.perf_counter() - start_time) * 1000

            if not chunks:
                raise ValueError("No response chunks received")

            return BenchmarkResult(
                model_id=model_id,
                success=True,
                latency_ms=latency_ms,
                speed_rating=self._calculate_speed_rating(latency_ms),
            )
        except Exception as e:
            return BenchmarkResult(
                model_id=model_id,
                success=False,
                error=str(e),
            )

    def _calculate_speed_rating(self, latency_ms: float) -> int:
        if latency_ms < 500:
            return 5
        elif latency_ms < 1000:
            return 4
        elif latency_ms < 2000:
            return 3
        elif latency_ms < 5000:
            return 2
        else:
            return 1

    async def generate_image(self, prompt: str, **kwargs: Any) -> ImageResult:
        """Generate an image from prompt using Pollinations GET endpoint."""
        params = {}
        for k, v in kwargs.items():
            if v is not None:
                params[k] = str(v)

        quoted_prompt = quote(prompt)
        url = f"https://gen.pollinations.ai/image/{quoted_prompt}"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=60.0)
            if response.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"Image generation failed with status {response.status_code}",
                    request=response.request,
                    response=response,
                )

            b64_data = base64.b64encode(response.content).decode("utf-8")
            mime_type = response.headers.get("content-type", "image/png")
            full_url = str(response.url)

            return ImageResult(
                url=full_url,
                b64_data=b64_data,
                mime_type=mime_type,
            )

    async def health_check(self) -> HealthStatus:
        """Lightweight liveness check."""
        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("https://gen.pollinations.ai/v1/models", timeout=5.0)
                latency_ms = (time.perf_counter() - start_time) * 1000
                if response.status_code == 200:
                    return HealthStatus(
                        healthy=True,
                        checked_at=datetime.now(UTC),
                        latency_ms=latency_ms,
                        detail="Successfully retrieved model list",
                    )
                else:
                    return HealthStatus(
                        healthy=False,
                        checked_at=datetime.now(UTC),
                        latency_ms=latency_ms,
                        detail=f"Unexpected status code: {response.status_code}",
                    )
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return HealthStatus(
                healthy=False,
                checked_at=datetime.now(UTC),
                latency_ms=latency_ms,
                detail=str(e),
            )

    def remaining_quota(self, usage_row: QuotaUsage) -> QuotaStatus:
        """Return the remaining quota (unbounded for Pollinations)."""
        return QuotaStatus(
            exhausted=False,
            remaining=None,
            limit=None,
            reset_at=None,
        )
