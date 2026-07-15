"""Ollama provider adapter.

Conforms strictly to the ProviderAdapter protocol.
Uses Ollama's OpenAI-compatible APIs at /v1.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
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


class OllamaAdapter(ProviderAdapter):
    """Adapter for local Ollama service."""

    name: str = "ollama"
    auth_type: Literal["api_key", "none", "local"] = "local"

    def __init__(self) -> None:
        # Default to local Ollama, allow override via env var
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")

    async def validate_key(self, api_key: str | None) -> bool:
        """Lightweight check for local Ollama. No key is needed."""
        return True

    async def discover_models(self, api_key: str | None) -> list[DiscoveredModel]:
        """Return the live list of models from Ollama's /v1/models endpoint."""
        url = f"{self.base_url}/models"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=5.0)
                if response.status_code != 200:
                    return []
                data = response.json()
                
                discovered_models = []
                for item in data.get("data", []):
                    model_id = item.get("id")
                    if not model_id:
                        continue
                    
                    # Set supports_vision if model ID implies it
                    supports_vision = any(
                        x in model_id.lower()
                        for x in ("vision", "llava", "bakllava", "minicpm", "moondream")
                    )
                    
                    discovered_models.append(
                        DiscoveredModel(
                            model_id=model_id,
                            display_name=model_id,
                            supports_vision=supports_vision,
                            context_length=8192,  # Default context window
                            raw_metadata=item,
                        )
                    )
                return discovered_models
        except (httpx.HTTPError, Exception):
            # If Ollama is down or fails, return an empty list as allowed by SPEC
            return []

    async def benchmark(self, model_id: str, api_key: str | None) -> BenchmarkResult:
        """Time one short fixed prompt ("Reply with the word OK.") against the model."""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply with the word OK."}],
            "stream": False,
            "max_tokens": 5,
        }
        
        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=10.0)
                latency_ms = (time.perf_counter() - start_time) * 1000
                
                if response.status_code != 200:
                    return BenchmarkResult(
                        model_id=model_id,
                        success=False,
                        error=f"HTTP {response.status_code}: {response.text}",
                    )
                
                # Bucketing speed rating 1-5 from latency_ms:
                # <500ms -> 5, <1000ms -> 4, <2000ms -> 3, <4000ms -> 2, otherwise 1
                if latency_ms < 500:
                    speed_rating = 5
                elif latency_ms < 1000:
                    speed_rating = 4
                elif latency_ms < 2000:
                    speed_rating = 3
                elif latency_ms < 4000:
                    speed_rating = 2
                else:
                    speed_rating = 1
                
                return BenchmarkResult(
                    model_id=model_id,
                    success=True,
                    latency_ms=latency_ms,
                    speed_rating=speed_rating,
                )
        except Exception as exc:
            return BenchmarkResult(
                model_id=model_id,
                success=False,
                error=str(exc),
            )

    async def chat(
        self, messages: list[Message], model_id: str, **kwargs: Any
    ) -> AsyncIterator[ChatChunk]:
        """Stream a chat completion for the given model."""
        url = f"{self.base_url}/chat/completions"
        
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

        payload = {
            "model": model_id,
            "messages": formatted_messages,
            "stream": True,
            **kwargs,
        }

        async def _stream_chat() -> AsyncIterator[ChatChunk]:
            async with (
                httpx.AsyncClient() as client,
                client.stream("POST", url, json=payload, timeout=30.0) as response,
            ):
                if response.status_code != 200:
                    await response.aread()
                    raise httpx.HTTPStatusError(
                        f"Ollama chat completion failed with status {response.status_code}",
                        request=response.request,
                        response=response,
                    )

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk_data = json.loads(data_str)
                            choices = chunk_data.get("choices", [])
                            if choices:
                                choice = choices[0]
                                delta = choice.get("delta", {})
                                content = delta.get("content", "")
                                finish_reason = choice.get("finish_reason")

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

        return _stream_chat()

    async def generate_image(self, prompt: str, **kwargs: Any) -> ImageResult:
        """Generate an image (unsupported by Ollama)."""
        raise NotImplementedError("Ollama provider does not support image generation.")

    async def health_check(self) -> HealthStatus:
        """Liveness check calling the models list endpoint."""
        url = f"{self.base_url}/models"
        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=2.0)
                latency_ms = (time.perf_counter() - start_time) * 1000
                if response.status_code == 200:
                    return HealthStatus(
                        healthy=True,
                        checked_at=datetime.now(UTC),
                        latency_ms=latency_ms,
                        detail="Ollama service is reachable",
                    )
                else:
                    return HealthStatus(
                        healthy=False,
                        checked_at=datetime.now(UTC),
                        detail=f"Ollama returned HTTP status {response.status_code}",
                    )
        except Exception as exc:
            return HealthStatus(
                healthy=False,
                checked_at=datetime.now(UTC),
                detail=str(exc),
            )

    def remaining_quota(self, usage_row: QuotaUsage) -> QuotaStatus:
        """Derive remaining quota. Ollama has no rate limit (unbounded)."""
        return QuotaStatus(
            exhausted=False,
            remaining=None,
            limit=None,
            reset_at=None,
        )
