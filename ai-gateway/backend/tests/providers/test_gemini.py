from __future__ import annotations

import datetime
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.providers.base import Message, MessageContentPart, QuotaUsage
from app.providers.gemini import GeminiAdapter


@pytest.fixture
def adapter() -> GeminiAdapter:
    return GeminiAdapter(base_url="https://mock-gemini.api")


async def test_validate_key_success(adapter: GeminiAdapter) -> None:
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        result = await adapter.validate_key("valid_key")

        assert result is True
        mock_get.assert_called_once_with(
            "https://mock-gemini.api/v1/models",
            headers={"Authorization": "Bearer valid_key"},
            timeout=5.0,
        )


async def test_validate_key_failure(adapter: GeminiAdapter) -> None:
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 401

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        result = await adapter.validate_key("invalid_key")

        assert result is False


async def test_validate_key_none_or_empty(adapter: GeminiAdapter) -> None:
    assert await adapter.validate_key(None) is False
    assert await adapter.validate_key("") is False


async def test_discover_models_success(adapter: GeminiAdapter) -> None:
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"id": "gemini-1.5-flash", "display_name": "Gemini 1.5 Flash"},
            {"id": "gemini-1.5-pro", "display_name": "Gemini 1.5 Pro"},
            {"id": "gemini-2.0-flash-exp"},
            {"id": "custom-model-vision"},
            {"id": "custom-pro-model"},
            {"id": "unknown-model"},
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        models = await adapter.discover_models("some_key")

        assert len(models) == 6

        # Test supports_vision mapping
        assert models[0].model_id == "gemini-1.5-flash"
        assert models[0].display_name == "Gemini 1.5 Flash"
        assert models[0].supports_vision is True
        assert models[0].context_length == 1048576

        assert models[1].model_id == "gemini-1.5-pro"
        assert models[1].supports_vision is True
        assert models[1].context_length == 2097152

        assert models[2].model_id == "gemini-2.0-flash-exp"
        assert models[2].supports_vision is True
        assert models[2].context_length == 1048576

        assert models[3].model_id == "custom-model-vision"
        assert models[3].supports_vision is True
        assert models[3].context_length == 128000

        assert models[4].model_id == "custom-pro-model"
        assert models[4].supports_vision is False
        assert models[4].context_length == 2097152

        assert models[5].model_id == "unknown-model"
        assert models[5].supports_vision is False
        assert models[5].context_length == 128000


async def test_discover_models_error(adapter: GeminiAdapter) -> None:
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.HTTPStatusError(
            "Unauthorized",
            request=MagicMock(spec=httpx.Request),
            response=MagicMock(spec=httpx.Response, status_code=401),
        )
        with pytest.raises(httpx.HTTPError):
            await adapter.discover_models("some_key")


async def test_discover_models_empty_or_none_key(adapter: GeminiAdapter) -> None:
    assert await adapter.discover_models(None) == []
    assert await adapter.discover_models("") == []


async def test_benchmark_success(adapter: GeminiAdapter) -> None:
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await adapter.benchmark("gemini-1.5-flash", "some_key")

        assert result.success is True
        assert result.model_id == "gemini-1.5-flash"
        assert result.latency_ms is not None
        assert result.speed_rating is not None
        assert result.error is None


async def test_benchmark_failure(adapter: GeminiAdapter) -> None:
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ConnectTimeout("Connection timed out")
        result = await adapter.benchmark("gemini-1.5-flash", "some_key")

        assert result.success is False
        assert result.model_id == "gemini-1.5-flash"
        assert result.latency_ms is None
        assert result.speed_rating is None
        assert result.error is not None
        assert "Connection timed out" in result.error


async def test_benchmark_missing_key(adapter: GeminiAdapter) -> None:
    result = await adapter.benchmark("gemini-1.5-flash", None)
    assert result.success is False
    assert result.error is not None
    assert "API key is missing" in result.error


class AsyncIteratorMock:
    def __init__(self, items: list[str]) -> None:
        self.items = items

    def __aiter__(self) -> AsyncIteratorMock:
        return self

    async def __anext__(self) -> str:
        if not self.items:
            raise StopAsyncIteration
        return self.items.pop(0)


class MockStreamResponse:
    def __init__(self, status_code: int, lines: list[str]) -> None:
        self.status_code = status_code
        self.lines = lines

    async def __aenter__(self) -> MockStreamResponse:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    async def read(self) -> bytes:
        return b""

    async def aread(self) -> bytes:
        return b""

    def raise_for_status(self) -> None:
        if self.status_code != 200:
            raise httpx.HTTPStatusError(
                "Error",
                request=MagicMock(spec=httpx.Request),
                response=MagicMock(spec=httpx.Response, status_code=self.status_code),
            )

    def aiter_lines(self) -> AsyncIteratorMock:
        return AsyncIteratorMock(self.lines)


async def test_chat_stream_success(adapter: GeminiAdapter) -> None:
    messages = [
        Message(role="system", content="You are a helper."),
        Message(
            role="user",
            content=[
                MessageContentPart(type="text", text="Hello"),
                MessageContentPart(type="image_url", image_url="http://example.com/image.png"),
            ],
        ),
    ]

    mock_lines = [
        "data: " + json.dumps({
            "choices": [{
                "delta": {"content": "Hello"},
                "finish_reason": None
            }]
        }),
        "data: " + json.dumps({
            "choices": [{
                "delta": {"content": " world"},
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5
            }
        }),
        "data: [DONE]"
    ]

    mock_stream = MockStreamResponse(status_code=200, lines=mock_lines)

    with patch("httpx.AsyncClient.stream") as mock_stream_method:
        mock_stream_method.return_value = mock_stream

        chunks = []
        async for chunk in adapter.chat(messages, "gemini-1.5-flash", api_key="some_key"):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].delta == "Hello"
        assert chunks[0].finish_reason is None
        assert chunks[0].tokens_in is None

        assert chunks[1].delta == " world"
        assert chunks[1].finish_reason == "stop"
        assert chunks[1].tokens_in == 10
        assert chunks[1].tokens_out == 5


async def test_chat_stream_http_error(adapter: GeminiAdapter) -> None:
    messages = [Message(role="user", content="Hello")]
    mock_stream = MockStreamResponse(status_code=401, lines=[])

    with patch("httpx.AsyncClient.stream") as mock_stream_method:
        mock_stream_method.return_value = mock_stream

        with pytest.raises(httpx.HTTPStatusError):
            async for _ in adapter.chat(messages, "gemini-1.5-flash", api_key="some_key"):
                pass


async def test_chat_stream_rate_limit_error(adapter: GeminiAdapter) -> None:
    messages = [Message(role="user", content="Hello")]
    mock_stream = MockStreamResponse(status_code=429, lines=[])

    with patch("httpx.AsyncClient.stream") as mock_stream_method:
        mock_stream_method.return_value = mock_stream

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            async for _ in adapter.chat(messages, "gemini-1.5-flash", api_key="some_key"):
                pass
        assert exc_info.value.response.status_code == 429


async def test_chat_missing_key(adapter: GeminiAdapter) -> None:
    messages = [Message(role="user", content="Hello")]
    with pytest.raises(ValueError, match="API key is required"):
        async for _ in adapter.chat(messages, "gemini-1.5-flash"):
            pass


async def test_generate_image_not_implemented(adapter: GeminiAdapter) -> None:
    with pytest.raises(NotImplementedError):
        await adapter.generate_image("A cute cat")


async def test_health_check_healthy(adapter: GeminiAdapter) -> None:
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 401

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        result = await adapter.health_check()

        assert result.healthy is True
        assert result.latency_ms is not None
        assert result.detail is not None
        assert "Reachable" in result.detail


async def test_health_check_unhealthy(adapter: GeminiAdapter) -> None:
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Connection failed")
        result = await adapter.health_check()

        assert result.healthy is False
        assert result.latency_ms is None
        assert result.detail is not None
        assert "Connection failed" in result.detail


def test_remaining_quota(adapter: GeminiAdapter) -> None:
    # Test case 1: normal usage within limit
    usage = QuotaUsage(
        provider_name="gemini",
        date=datetime.date(2026, 7, 15),
        request_count=100,
        daily_limit=1500,
    )
    status = adapter.remaining_quota(usage)
    assert status.exhausted is False
    assert status.remaining == 1400
    assert status.limit == 1500
    assert status.reset_at == datetime.datetime(2026, 7, 16, 0, 0, tzinfo=datetime.UTC)

    # Test case 2: exhausted
    usage_exhausted = QuotaUsage(
        provider_name="gemini",
        date=datetime.date(2026, 7, 15),
        request_count=1600,
        daily_limit=1500,
    )
    status_exhausted = adapter.remaining_quota(usage_exhausted)
    assert status_exhausted.exhausted is True
    assert status_exhausted.remaining == 0

    # Test case 3: default daily limit
    usage_default = QuotaUsage(
        provider_name="gemini",
        date=datetime.date(2026, 7, 15),
        request_count=500,
        daily_limit=None,
    )
    status_default = adapter.remaining_quota(usage_default)
    assert status_default.limit == 1500
    assert status_default.remaining == 1000
