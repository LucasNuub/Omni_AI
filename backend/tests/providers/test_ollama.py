"""Tests for the Ollama provider adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.providers.base import Message, QuotaUsage
from app.providers.ollama import OllamaAdapter


@pytest.fixture
def adapter() -> OllamaAdapter:
    return OllamaAdapter()


async def test_validate_key(adapter: OllamaAdapter) -> None:
    # Ollama is local and needs no key validation, should always return True
    assert await adapter.validate_key(None) is True
    assert await adapter.validate_key("any-key") is True


async def test_discover_models_success(adapter: OllamaAdapter) -> None:
    mock_response = httpx.Response(
        200,
        json={
            "data": [
                {"id": "llama3:latest", "object": "model"},
                {"id": "llava:latest", "object": "model"},
            ]
        }
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        models = await adapter.discover_models(None)

    assert len(models) == 2
    assert models[0].model_id == "llama3:latest"
    assert models[0].supports_vision is False
    assert models[1].model_id == "llava:latest"
    assert models[1].supports_vision is True


async def test_discover_models_http_error(adapter: OllamaAdapter) -> None:
    mock_response = httpx.Response(500, text="Internal Server Error")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        models = await adapter.discover_models(None)

    # Errors should be caught and return an empty list
    assert models == []


async def test_discover_models_exception(adapter: OllamaAdapter) -> None:
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Connection failed")
        models = await adapter.discover_models(None)

    assert models == []


async def test_benchmark_success(adapter: OllamaAdapter) -> None:
    mock_response = httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        res = await adapter.benchmark("llama3", None)

    assert res.success is True
    assert res.latency_ms is not None
    assert res.speed_rating in (1, 2, 3, 4, 5)
    assert res.error is None


async def test_benchmark_failure(adapter: OllamaAdapter) -> None:
    mock_response = httpx.Response(500, text="Internal Server Error")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        res = await adapter.benchmark("llama3", None)

    assert res.success is False
    assert res.latency_ms is None
    assert res.speed_rating is None
    assert res.error is not None
    assert "HTTP 500" in res.error


async def test_benchmark_timeout(adapter: OllamaAdapter) -> None:
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Timeout")
        res = await adapter.benchmark("llama3", None)

    assert res.success is False
    assert res.latency_ms is None
    assert res.speed_rating is None
    assert res.error is not None
    assert "Timeout" in res.error


async def test_chat_success(adapter: OllamaAdapter) -> None:
    class AsyncStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b'data: {"choices": [{"delta": {"content": "Hello"}, "finish_reason": null}]}\n'
            yield b'data: {"choices": [{"delta": {"content": "!"}, "finish_reason": "stop"}]}\n'
            yield b'data: [DONE]\n'

    mock_response = httpx.Response(
        200,
        request=httpx.Request("POST", "http://localhost:11434/v1/chat/completions"),
        stream=AsyncStream()
    )

    mock_stream = AsyncMock()
    mock_stream.__aenter__.return_value = mock_response

    messages = [
        Message(role="user", content="Hi"),
    ]

    with patch("httpx.AsyncClient.stream") as mock_stream_method:
        mock_stream_method.return_value = mock_stream
        chunks = []
        async for chunk in await adapter.chat(messages, "llama3"):
            chunks.append(chunk)

    assert len(chunks) == 2
    assert chunks[0].delta == "Hello"
    assert chunks[0].finish_reason is None
    assert chunks[1].delta == "!"
    assert chunks[1].finish_reason == "stop"


async def test_chat_error(adapter: OllamaAdapter) -> None:
    mock_response = AsyncMock()
    mock_response.status_code = 429
    mock_response.aread.return_value = b"Rate limit exceeded"
    mock_response.request = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")

    mock_stream = AsyncMock()
    mock_stream.__aenter__.return_value = mock_response

    messages = [Message(role="user", content="Hi")]

    with patch("httpx.AsyncClient.stream") as mock_stream_method:
        mock_stream_method.return_value = mock_stream
        stream = await adapter.chat(messages, "llama3")
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            async for _ in stream:
                pass
        assert exc_info.value.response.status_code == 429


async def test_chat_json_decode_error(adapter: OllamaAdapter) -> None:
    class AsyncStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"data: invalid-json\n"
            yield b'data: {"choices": [{"delta": {"content": "OK"}}]}\n'
            yield b"data: [DONE]\n"

    mock_response = httpx.Response(
        200,
        request=httpx.Request("POST", "http://localhost:11434/v1/chat/completions"),
        stream=AsyncStream()
    )

    mock_stream = AsyncMock()
    mock_stream.__aenter__.return_value = mock_response

    messages = [Message(role="user", content="Hi")]

    with patch("httpx.AsyncClient.stream") as mock_stream_method:
        mock_stream_method.return_value = mock_stream
        chunks = []
        async for chunk in await adapter.chat(messages, "llama3"):
            chunks.append(chunk)

    # Should skip the malformed line and return the valid one
    assert len(chunks) == 1
    assert chunks[0].delta == "OK"


async def test_generate_image(adapter: OllamaAdapter) -> None:
    with pytest.raises(NotImplementedError):
        await adapter.generate_image("A cute cat")


async def test_health_check_healthy(adapter: OllamaAdapter) -> None:
    mock_response = httpx.Response(200, json={})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        status = await adapter.health_check()

    assert status.healthy is True
    assert status.latency_ms is not None
    assert status.detail == "Ollama service is reachable"


async def test_health_check_unhealthy(adapter: OllamaAdapter) -> None:
    mock_response = httpx.Response(500, text="Internal Server Error")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        status = await adapter.health_check()

    assert status.healthy is False
    assert status.latency_ms is None
    assert status.detail is not None
    assert "returned HTTP status 500" in status.detail


async def test_health_check_exception(adapter: OllamaAdapter) -> None:
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = Exception("Connection refused")
        status = await adapter.health_check()

    assert status.healthy is False
    assert status.latency_ms is None
    assert status.detail is not None
    assert "Connection refused" in status.detail


def test_remaining_quota(adapter: OllamaAdapter) -> None:
    usage = QuotaUsage(
        provider_name="ollama",
        date=date(2026, 7, 15),
        request_count=100,
        daily_limit=None,
    )
    status = adapter.remaining_quota(usage)
    assert status.exhausted is False
    assert status.remaining is None
    assert status.limit is None
    assert status.reset_at is None
