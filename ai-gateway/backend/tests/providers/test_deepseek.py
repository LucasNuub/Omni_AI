from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.providers.base import Message, QuotaUsage
from app.providers.deepseek import DeepSeekAdapter


@pytest.fixture
def adapter() -> DeepSeekAdapter:
    return DeepSeekAdapter(base_url="https://api.deepseek.com")


async def test_validate_key_success(adapter: DeepSeekAdapter) -> None:
    mock_response = httpx.Response(200, json={"data": []})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        result = await adapter.validate_key("valid_key")
        assert result is True
        mock_get.assert_called_once_with(
            "https://api.deepseek.com/models",
            headers={"Authorization": "Bearer valid_key"},
            timeout=5.0,
        )


async def test_validate_key_invalid(adapter: DeepSeekAdapter) -> None:
    mock_response = httpx.Response(401, json={"error": "Invalid API Key"})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        result = await adapter.validate_key("invalid_key")
        assert result is False


async def test_validate_key_exception(adapter: DeepSeekAdapter) -> None:
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Connection failed")
        result = await adapter.validate_key("any_key")
        assert result is False


async def test_discover_models_success(adapter: DeepSeekAdapter) -> None:
    mock_models_response = {
        "data": [
            {"id": "deepseek-chat", "context_window": 128000},
            {"id": "deepseek-reasoner"},
            {"id": "unknown-model"},
        ]
    }
    mock_response = httpx.Response(200, json=mock_models_response)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        models = await adapter.discover_models("valid_key")

        assert len(models) == 3

        # First model (deepseek-chat)
        assert models[0].model_id == "deepseek-chat"
        assert models[0].display_name == "Deepseek Chat"
        assert models[0].supports_vision is False
        assert models[0].context_length == 128000

        # Second model (deepseek-reasoner)
        assert models[1].model_id == "deepseek-reasoner"
        assert models[1].display_name == "Deepseek Reasoner"
        assert models[1].supports_vision is False
        assert models[1].context_length == 128000

        # Third model (Unknown)
        assert models[2].model_id == "unknown-model"
        assert models[2].supports_vision is False
        assert models[2].context_length is None


async def test_discover_models_error_or_empty(adapter: DeepSeekAdapter) -> None:
    mock_response = httpx.Response(500, text="Internal Error")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        models = await adapter.discover_models("valid_key")
        assert models == []

    # Test key is None
    models_no_key = await adapter.discover_models(None)
    assert models_no_key == []


async def test_benchmark_success(adapter: DeepSeekAdapter) -> None:
    mock_response = httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await adapter.benchmark("deepseek-chat", "valid_key")

        assert result.model_id == "deepseek-chat"
        assert result.success is True
        assert result.latency_ms is not None
        assert result.latency_ms > 0
        assert result.speed_rating is not None
        assert 1 <= result.speed_rating <= 5
        assert result.error is None


async def test_benchmark_failure(adapter: DeepSeekAdapter) -> None:
    mock_response = httpx.Response(400, text="Bad Request")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await adapter.benchmark("deepseek-chat", "valid_key")

        assert result.success is False
        assert result.error is not None
        assert "benchmark failed" in result.error.lower()


async def test_benchmark_timeout_or_exception(adapter: DeepSeekAdapter) -> None:
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Timeout")
        result = await adapter.benchmark("deepseek-chat", "valid_key")

        assert result.success is False
        assert result.error is not None
        assert "timeout" in result.error.lower()


async def test_chat_success_stream(adapter: DeepSeekAdapter) -> None:
    messages = [
        Message(role="system", content="You are a helper."),
        Message(role="user", content="Hello!"),
    ]

    async def mock_aiter_lines() -> AsyncIterator[str]:
        yield (
            'data: {"choices": [{"delta": {"content": "Hello"}, "finish_reason": null}], '
            '"usage": {"prompt_tokens": 10, "completion_tokens": 5}}'
        )
        yield 'data: {"choices": [{"delta": {"content": " world!"}, "finish_reason": "stop"}]}'
        yield 'data: [DONE]'

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.aiter_lines = mock_aiter_lines

    mock_stream = AsyncMock()
    mock_stream.__aenter__.return_value = mock_response

    with patch("httpx.AsyncClient.stream") as mock_stream_method:
        mock_stream_method.return_value = mock_stream

        chunks = []
        async for chunk in adapter.chat(messages, "deepseek-chat", api_key="valid_key"):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].delta == "Hello"
        assert chunks[0].finish_reason is None
        assert chunks[0].tokens_in == 10
        assert chunks[0].tokens_out == 5

        assert chunks[1].delta == " world!"
        assert chunks[1].finish_reason == "stop"
        assert chunks[1].tokens_in is None


async def test_chat_error_status(adapter: DeepSeekAdapter) -> None:
    messages = [Message(role="user", content="Hi")]

    mock_response = AsyncMock()
    mock_response.status_code = 429
    mock_response.aread.return_value = b"Rate limit exceeded"
    mock_response.request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")

    mock_stream = AsyncMock()
    mock_stream.__aenter__.return_value = mock_response

    with patch("httpx.AsyncClient.stream") as mock_stream_method:
        mock_stream_method.return_value = mock_stream

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            async for _ in adapter.chat(messages, "deepseek-chat", api_key="valid_key"):
                pass
        assert exc_info.value.response.status_code == 429
        assert "Rate limit exceeded" in str(exc_info.value)


async def test_chat_missing_key(adapter: DeepSeekAdapter) -> None:
    messages = [Message(role="user", content="Hi")]
    with pytest.raises(ValueError) as exc_info:
        async for _ in adapter.chat(messages, "deepseek-chat"):
            pass
    assert "api key is required" in str(exc_info.value).lower()


def test_remaining_quota(adapter: DeepSeekAdapter) -> None:
    # 1. Under limit with custom limit
    usage1 = QuotaUsage(
        provider_name="deepseek",
        date=date(2026, 7, 15),
        request_count=100,
        daily_limit=500,
    )
    status1 = adapter.remaining_quota(usage1)
    assert status1.exhausted is False
    assert status1.remaining == 400
    assert status1.limit == 500
    assert status1.reset_at == datetime(2026, 7, 16, 0, 0, tzinfo=UTC)

    # 2. Exceeded limit
    usage2 = QuotaUsage(
        provider_name="deepseek",
        date=date(2026, 7, 15),
        request_count=1100,
        daily_limit=1000,
    )
    status2 = adapter.remaining_quota(usage2)
    assert status2.exhausted is True
    assert status2.remaining == 0

    # 3. Default limit (1000 RPD)
    usage3 = QuotaUsage(
        provider_name="deepseek",
        date=date(2026, 7, 15),
        request_count=400,
        daily_limit=None,
    )
    status3 = adapter.remaining_quota(usage3)
    assert status3.limit == 1000
    assert status3.remaining == 600


async def test_generate_image_not_implemented(adapter: DeepSeekAdapter) -> None:
    with pytest.raises(NotImplementedError):
        await adapter.generate_image("A futuristic city")


async def test_health_check_healthy(adapter: DeepSeekAdapter) -> None:
    # API reachable (200 is healthy)
    mock_response = httpx.Response(200, json={})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        status = await adapter.health_check()
        assert status.healthy is True
        assert status.latency_ms is not None

    # API reachable but unauthorized (401 is still healthy / up)
    mock_response_401 = httpx.Response(401, json={})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response_401
        status = await adapter.health_check()
        assert status.healthy is True


async def test_health_check_unhealthy(adapter: DeepSeekAdapter) -> None:
    # Server error 500
    mock_response = httpx.Response(500, text="Internal Server Error")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        status = await adapter.health_check()
        assert status.healthy is False

    # Connection failure
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectTimeout("Connection timed out")
        status = await adapter.health_check()
        assert status.healthy is False
