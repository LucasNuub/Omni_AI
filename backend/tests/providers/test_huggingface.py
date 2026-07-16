from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.providers.base import Message, QuotaUsage
from app.providers.huggingface import HuggingFaceAdapter


@pytest.fixture
def adapter() -> HuggingFaceAdapter:
    return HuggingFaceAdapter(base_url="https://router.huggingface.co/v1")


async def test_validate_key_success(adapter: HuggingFaceAdapter) -> None:
    mock_response = httpx.Response(200, json={"data": []})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        result = await adapter.validate_key("valid_key")
        assert result is True
        mock_get.assert_called_once_with(
            "https://router.huggingface.co/v1/models",
            headers={"Authorization": "Bearer valid_key"},
            timeout=5.0,
        )


async def test_validate_key_invalid(adapter: HuggingFaceAdapter) -> None:
    mock_response = httpx.Response(401, json={"error": "Invalid API Key"})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        result = await adapter.validate_key("invalid_key")
        assert result is False


async def test_validate_key_exception(adapter: HuggingFaceAdapter) -> None:
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Connection failed")
        result = await adapter.validate_key("any_key")
        assert result is False


async def test_discover_models_success(adapter: HuggingFaceAdapter) -> None:
    mock_models_response = {
        "data": [
            {"id": "meta-llama/Llama-3-8b-instruct", "context_window": 8192},
            {"id": "meta-llama/Llama-3.2-11b-vision-preview"},
            {"id": "unknown-model"},
        ]
    }
    mock_response = httpx.Response(200, json=mock_models_response)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        models = await adapter.discover_models("valid_key")

        assert len(models) == 3

        # First model (Llama-3-8b-instruct)
        assert models[0].model_id == "meta-llama/Llama-3-8b-instruct"
        assert models[0].display_name == "Llama 3 8b Instruct"
        assert models[0].supports_vision is False
        assert models[0].context_length == 8192

        # Second model (Vision preview)
        assert models[1].model_id == "meta-llama/Llama-3.2-11b-vision-preview"
        assert models[1].display_name == "Llama 3.2 11b Vision Preview"
        assert models[1].supports_vision is True
        assert models[1].context_length == 131072  # Guessed from llama-3.2

        # Third model (Unknown)
        assert models[2].model_id == "unknown-model"
        assert models[2].supports_vision is False
        assert models[2].context_length is None


async def test_discover_models_error_or_empty(adapter: HuggingFaceAdapter) -> None:
    mock_response = httpx.Response(500, text="Internal Error")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        models = await adapter.discover_models("valid_key")
        assert models == []

    # Test key is None
    models_no_key = await adapter.discover_models(None)
    assert models_no_key == []


async def test_benchmark_success(adapter: HuggingFaceAdapter) -> None:
    mock_response = httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await adapter.benchmark("meta-llama/Llama-3-8b-instruct", "valid_key")

        assert result.model_id == "meta-llama/Llama-3-8b-instruct"
        assert result.success is True
        assert result.latency_ms is not None
        assert result.latency_ms > 0
        assert result.speed_rating is not None
        assert 1 <= result.speed_rating <= 5
        assert result.error is None


async def test_benchmark_failure(adapter: HuggingFaceAdapter) -> None:
    mock_response = httpx.Response(400, text="Bad Request")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await adapter.benchmark("meta-llama/Llama-3-8b-instruct", "valid_key")

        assert result.success is False
        assert result.error is not None
        assert "benchmark failed" in result.error.lower()


async def test_benchmark_timeout_or_exception(adapter: HuggingFaceAdapter) -> None:
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Timeout")
        result = await adapter.benchmark("meta-llama/Llama-3-8b-instruct", "valid_key")

        assert result.success is False
        assert result.error is not None
        assert "timeout" in result.error.lower()


async def test_chat_success_stream(adapter: HuggingFaceAdapter) -> None:
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
        async for chunk in adapter.chat(
            messages, "meta-llama/Llama-3-8b-instruct", api_key="valid_key"
        ):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].delta == "Hello"
        assert chunks[0].finish_reason is None
        assert chunks[0].tokens_in == 10
        assert chunks[0].tokens_out == 5

        assert chunks[1].delta == " world!"
        assert chunks[1].finish_reason == "stop"
        assert chunks[1].tokens_in is None


async def test_chat_error_status(adapter: HuggingFaceAdapter) -> None:
    messages = [Message(role="user", content="Hi")]

    mock_response = AsyncMock()
    mock_response.status_code = 429
    mock_response.aread.return_value = b"Rate limit exceeded"
    mock_response.request = httpx.Request("POST", "https://router.huggingface.co/v1/chat/completions")

    mock_stream = AsyncMock()
    mock_stream.__aenter__.return_value = mock_response

    with patch("httpx.AsyncClient.stream") as mock_stream_method:
        mock_stream_method.return_value = mock_stream

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            async for _ in adapter.chat(
                messages, "meta-llama/Llama-3-8b-instruct", api_key="valid_key"
            ):
                pass
        assert exc_info.value.response.status_code == 429
        assert "Rate limit exceeded" in str(exc_info.value)


async def test_chat_missing_key(adapter: HuggingFaceAdapter) -> None:
    messages = [Message(role="user", content="Hi")]
    with pytest.raises(ValueError) as exc_info:
        async for _ in adapter.chat(messages, "meta-llama/Llama-3-8b-instruct"):
            pass
    assert "api key is required" in str(exc_info.value).lower()


def test_remaining_quota(adapter: HuggingFaceAdapter) -> None:
    # 1. Under limit with custom limit
    usage1 = QuotaUsage(
        provider_name="huggingface",
        date=date(2026, 7, 15),
        request_count=200,
        daily_limit=500,
    )
    status1 = adapter.remaining_quota(usage1)
    assert status1.exhausted is False
    assert status1.remaining == 300
    assert status1.limit == 500
    assert status1.reset_at == datetime(2026, 7, 16, 0, 0, tzinfo=UTC)

    # 2. Exceeded limit
    usage2 = QuotaUsage(
        provider_name="huggingface",
        date=date(2026, 7, 15),
        request_count=1200,
        daily_limit=1000,
    )
    status2 = adapter.remaining_quota(usage2)
    assert status2.exhausted is True
    assert status2.remaining == 0

    # 3. Default limit
    usage3 = QuotaUsage(
        provider_name="huggingface",
        date=date(2026, 7, 15),
        request_count=300,
        daily_limit=None,
    )
    status3 = adapter.remaining_quota(usage3)
    assert status3.limit == 1000
    assert status3.remaining == 700


async def test_generate_image_success(adapter: HuggingFaceAdapter) -> None:
    fake_png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR..."
    expected_b64 = base64.b64encode(fake_png_data).decode("utf-8")
    mock_response = httpx.Response(
        200,
        content=fake_png_data,
        headers={"content-type": "image/png"}
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await adapter.generate_image("A futuristic city", api_key="valid_key")

        assert result.b64_data == expected_b64
        assert result.mime_type == "image/png"
        assert result.url is None

        mock_post.assert_called_once_with(
            "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell",
            headers={"Authorization": "Bearer valid_key", "Content-Type": "application/json"},
            json={"inputs": "A futuristic city"},
            timeout=60.0,
        )


async def test_generate_image_custom_model(adapter: HuggingFaceAdapter) -> None:
    fake_jpeg_data = b"\xff\xd8\xff\xe0..."
    expected_b64 = base64.b64encode(fake_jpeg_data).decode("utf-8")
    mock_response = httpx.Response(
        200,
        content=fake_jpeg_data,
        headers={"content-type": "image/jpeg"}
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await adapter.generate_image(
            "A painting of a cat",
            api_key="valid_key",
            model_id="stabilityai/stable-diffusion-2-1"
        )

        assert result.b64_data == expected_b64
        assert result.mime_type == "image/jpeg"
        assert result.url is None

        mock_post.assert_called_once_with(
            "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-2-1",
            headers={"Authorization": "Bearer valid_key", "Content-Type": "application/json"},
            json={"inputs": "A painting of a cat"},
            timeout=60.0,
        )


async def test_generate_image_missing_key(adapter: HuggingFaceAdapter) -> None:
    with pytest.raises(ValueError) as exc_info:
        await adapter.generate_image("A cute kitten")
    assert "api key is required" in str(exc_info.value).lower()


async def test_generate_image_failure(adapter: HuggingFaceAdapter) -> None:
    mock_request = httpx.Request("POST", "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell")
    mock_response = httpx.Response(500, text="Model is loading", request=mock_request)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await adapter.generate_image("A cute kitten", api_key="valid_key")
        assert exc_info.value.response.status_code == 500


async def test_health_check_healthy(adapter: HuggingFaceAdapter) -> None:
    mock_response = httpx.Response(200, json={})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        status = await adapter.health_check()
        assert status.healthy is True
        assert status.latency_ms is not None

    mock_response_401 = httpx.Response(401, json={})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response_401
        status = await adapter.health_check()
        assert status.healthy is True


async def test_health_check_unhealthy(adapter: HuggingFaceAdapter) -> None:
    mock_response = httpx.Response(500, text="Internal Server Error")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        status = await adapter.health_check()
        assert status.healthy is False

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectTimeout("Connection timed out")
        status = await adapter.health_check()
        assert status.healthy is False
