from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.providers.base import ChatChunk, Message, QuotaUsage
from app.providers.pollinations import STATIC_MODELS, PollinationsAdapter


async def test_validate_key() -> None:
    adapter = PollinationsAdapter()
    assert await adapter.validate_key(None) is True
    assert await adapter.validate_key("any-key") is True


async def test_discover_models_success() -> None:
    adapter = PollinationsAdapter()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {
                "id": "openai",
                "context_length": 400000,
                "input_modalities": ["text", "image"],
            },
            {
                "id": "mistral-vision",
                "context_length": 262144,
                "input_modalities": ["text"],
            },
        ]
    }

    with patch("app.providers.pollinations.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        models = await adapter.discover_models(None)

        assert len(models) == 2
        assert models[0].model_id == "openai"
        assert models[0].supports_vision is True
        assert models[0].context_length == 400000

        assert models[1].model_id == "mistral-vision"
        assert models[1].supports_vision is True
        assert models[1].context_length == 262144

        mock_client.get.assert_called_once_with(
            "https://gen.pollinations.ai/v1/models",
            headers={"Authorization": ""},
            timeout=10.0,
        )


async def test_discover_models_failure() -> None:
    adapter = PollinationsAdapter()

    with patch("app.providers.pollinations.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.RequestError("API Down"))
        mock_client_class.return_value.__aenter__.return_value = mock_client

        models = await adapter.discover_models(None)

        # Should return static models
        assert len(models) == len(STATIC_MODELS)
        assert models[0].model_id == "openai"
        assert models[0].context_length == 400000


async def test_discover_models_non_200() -> None:
    adapter = PollinationsAdapter()
    mock_response = MagicMock()
    mock_response.status_code = 500

    with patch("app.providers.pollinations.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        models = await adapter.discover_models(None)

        assert len(models) == len(STATIC_MODELS)


async def test_chat_success() -> None:
    adapter = PollinationsAdapter()
    messages = [Message(role="user", content="hello")]

    mock_response = MagicMock()
    mock_response.status_code = 200

    async def mock_aiter_lines() -> AsyncIterator[str]:
        chunk1 = {
            "choices": [{"delta": {"content": "Hello"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        chunk2 = {"choices": [{"delta": {"content": " world"}, "finish_reason": "stop"}]}
        yield "data: " + json.dumps(chunk1)
        yield "data: " + json.dumps(chunk2)
        yield "data: [DONE]"

    mock_response.aiter_lines = MagicMock(return_value=mock_aiter_lines())

    with patch("app.providers.pollinations.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.stream.return_value.__aenter__.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        chunks = []
        async for chunk in adapter.chat(messages, "openai"):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].delta == "Hello"
        assert chunks[0].tokens_in == 10
        assert chunks[0].tokens_out == 5
        assert chunks[1].delta == " world"
        assert chunks[1].finish_reason == "stop"

        mock_client.stream.assert_called_once()
        call_args = mock_client.stream.call_args
        assert call_args is not None
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "https://gen.pollinations.ai/v1/chat/completions"
        assert call_args[1]["json"]["model"] == "openai"
        assert call_args[1]["json"]["stream"] is True


async def test_chat_rate_limited_429() -> None:
    adapter = PollinationsAdapter()
    messages = [Message(role="user", content="hello")]

    mock_response = AsyncMock()
    mock_response.status_code = 429
    mock_response.aread = AsyncMock(return_value=b"Rate limit exceeded")
    mock_response.request = httpx.Request("POST", "https://gen.pollinations.ai/v1/chat/completions")

    with patch("app.providers.pollinations.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.stream.return_value.__aenter__.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            async for _ in adapter.chat(messages, "openai"):
                pass

        assert exc_info.value.response.status_code == 429
        assert "Rate limit exceeded" in str(exc_info.value)


async def test_chat_timeout() -> None:
    adapter = PollinationsAdapter()
    messages = [Message(role="user", content="hello")]

    with patch("app.providers.pollinations.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.stream.side_effect = httpx.TimeoutException("Request timed out")
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(httpx.TimeoutException):
            async for _ in adapter.chat(messages, "openai"):
                pass


async def test_benchmark_success() -> None:
    adapter = PollinationsAdapter()

    async def mock_chat(
        messages: list[Message], model_id: str, **kwargs: Any
    ) -> AsyncIterator[ChatChunk]:
        yield ChatChunk(delta="OK")

    with patch.object(PollinationsAdapter, "chat", side_effect=mock_chat) as mock_chat_method:
        res = await adapter.benchmark("openai", None)
        assert res.success is True
        assert res.model_id == "openai"
        assert res.latency_ms is not None
        assert res.latency_ms > 0
        assert res.speed_rating is not None
        mock_chat_method.assert_called_once()


async def test_benchmark_failure() -> None:
    adapter = PollinationsAdapter()

    async def mock_chat_fail(
        messages: list[Message], model_id: str, **kwargs: Any
    ) -> AsyncIterator[ChatChunk]:
        raise ValueError("Timeout or chat failure")
        yield  # Make it an async generator

    with patch.object(PollinationsAdapter, "chat", side_effect=mock_chat_fail):
        res = await adapter.benchmark("openai", None)
        assert res.success is False
        assert res.model_id == "openai"
        assert res.error is not None
        assert "Timeout or chat failure" in res.error
        assert res.speed_rating is None


def test_remaining_quota() -> None:
    adapter = PollinationsAdapter()
    usage = QuotaUsage(
        provider_name="pollinations",
        date=date(2026, 1, 1),
        request_count=150,
        daily_limit=None,
    )
    status = adapter.remaining_quota(usage)
    assert status.exhausted is False
    assert status.remaining is None
    assert status.limit is None
    assert status.reset_at is None


async def test_generate_image_success() -> None:
    adapter = PollinationsAdapter()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"fake-image-bytes"
    mock_response.headers = {"content-type": "image/png"}
    mock_response.url = httpx.URL("https://gen.pollinations.ai/image/a%20cute%20cat?model=flux")

    with patch("app.providers.pollinations.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        res = await adapter.generate_image("a cute cat", model="flux")

        assert res.url == "https://gen.pollinations.ai/image/a%20cute%20cat?model=flux"
        assert res.b64_data == base64.b64encode(b"fake-image-bytes").decode("utf-8")
        assert res.mime_type == "image/png"

        mock_client.get.assert_called_once_with(
            "https://gen.pollinations.ai/image/a%20cute%20cat",
            params={"model": "flux"},
            timeout=60.0,
        )


async def test_generate_image_failure() -> None:
    adapter = PollinationsAdapter()
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.request = httpx.Request("GET", "https://gen.pollinations.ai/image/cat")

    with patch("app.providers.pollinations.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await adapter.generate_image("cat")


async def test_health_check_healthy() -> None:
    adapter = PollinationsAdapter()
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("app.providers.pollinations.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        status = await adapter.health_check()
        assert status.healthy is True
        assert status.latency_ms is not None
        assert status.latency_ms > 0
        assert status.detail is not None
        assert "Successfully retrieved model list" in status.detail


async def test_health_check_unhealthy() -> None:
    adapter = PollinationsAdapter()
    mock_response = MagicMock()
    mock_response.status_code = 503

    with patch("app.providers.pollinations.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        status = await adapter.health_check()
        assert status.healthy is False
        assert status.latency_ms is not None
        assert status.latency_ms > 0
        assert status.detail is not None
        assert "Unexpected status code: 503" in status.detail


async def test_health_check_exception() -> None:
    adapter = PollinationsAdapter()

    with patch("app.providers.pollinations.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client_class.return_value.__aenter__.return_value = mock_client

        status = await adapter.health_check()
        assert status.healthy is False
        assert status.detail is not None
        assert "Connection refused" in status.detail
