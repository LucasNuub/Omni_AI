from __future__ import annotations

from collections.abc import AsyncIterator, Generator
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.providers.base import Message, MessageContentPart, QuotaUsage
from app.providers.openrouter import OpenRouterAdapter

# --- Mock Classes for httpx Client Responses -----------------------------------------

class MockResponse:
    def __init__(
        self,
        status_code: int,
        json_data: dict[str, Any] | None = None,
        text_content: str = "",
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text_content

    def json(self) -> dict[str, Any]:
        return self._json_data

    async def aread(self) -> bytes:
        return self.text.encode("utf-8")


class MockStreamResponse:
    def __init__(
        self,
        status_code: int,
        lines: list[bytes] | None = None,
        error_text: str = "",
    ) -> None:
        self.status_code = status_code
        self._lines = lines or []
        self._error_text = error_text
        self.request = MagicMock()

    async def __aenter__(self) -> MockStreamResponse:
        return self

    async def __aexit__(
        self,
        exc_type: type | None,
        exc_val: Exception | None,
        exc_tb: Any,
    ) -> None:
        pass

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line.decode("utf-8")

    async def aread(self) -> bytes:
        return self._error_text.encode("utf-8")


class MockAsyncClient:
    def __init__(
        self,
        get_response: MockResponse | Exception | None = None,
        post_response: MockResponse | Exception | None = None,
        stream_response: MockStreamResponse | Exception | None = None,
    ) -> None:
        self.get_response = get_response
        self.post_response = post_response
        self.stream_response = stream_response
        self.calls: list[tuple[Any, ...]] = []

    async def __aenter__(self) -> MockAsyncClient:
        return self

    async def __aexit__(
        self,
        exc_type: type | None,
        exc_val: Exception | None,
        exc_tb: Any,
    ) -> None:
        pass

    async def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> MockResponse:
        self.calls.append(("get", url, headers, timeout))
        if isinstance(self.get_response, Exception):
            raise self.get_response
        if self.get_response is None:
            return MockResponse(200)
        return self.get_response

    async def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> MockResponse:
        self.calls.append(("post", url, headers, json, timeout))
        if isinstance(self.post_response, Exception):
            raise self.post_response
        if self.post_response is None:
            return MockResponse(200)
        return self.post_response

    def stream(
        self,
        method: str,
        url: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> MockStreamResponse:
        self.calls.append(("stream", method, url, json, headers, timeout))
        if isinstance(self.stream_response, Exception):
            raise self.stream_response
        if self.stream_response is None:
            return MockStreamResponse(200)
        return self.stream_response


@pytest.fixture
def mock_client() -> Generator[MockAsyncClient, None, None]:
    client = MockAsyncClient()
    with patch("httpx.AsyncClient", return_value=client):
        yield client


# --- Validate Key Tests ---------------------------------------------------------------

async def test_validate_key_success(mock_client: MockAsyncClient) -> None:
    mock_client.get_response = MockResponse(status_code=200)
    adapter = OpenRouterAdapter()
    assert await adapter.validate_key("valid-key") is True
    assert mock_client.calls[0][1] == "https://openrouter.ai/api/v1/key"
    assert mock_client.calls[0][2] == {"Authorization": "Bearer valid-key"}


async def test_validate_key_invalid(mock_client: MockAsyncClient) -> None:
    mock_client.get_response = MockResponse(status_code=401)
    adapter = OpenRouterAdapter()
    assert await adapter.validate_key("invalid-key") is False


async def test_validate_key_exception(mock_client: MockAsyncClient) -> None:
    mock_client.get_response = httpx.ConnectError("Connection failed")
    adapter = OpenRouterAdapter()
    assert await adapter.validate_key("any-key") is False


async def test_validate_key_missing() -> None:
    adapter = OpenRouterAdapter()
    assert await adapter.validate_key(None) is False
    assert await adapter.validate_key("") is False


# --- Discover Models Tests -------------------------------------------------------------

async def test_discover_models_success(mock_client: MockAsyncClient) -> None:
    mock_data = {
        "data": [
            {
                "id": "google/gemini-2-free",
                "name": "Gemini 2 Free",
                "pricing": {"prompt": "0.0", "completion": "0.0"},
                "context_length": 8192,
                "architecture": {"input_modalities": ["text"]},
            },
            {
                "id": "openai/gpt-4-vision-free",
                "name": "GPT-4 Vision Free",
                "pricing": {"prompt": "0", "completion": "0"},
                "context_length": 128000,
                "architecture": {"input_modalities": ["text", "image"]},
            },
            {
                "id": "anthropic/claude-3",
                "name": "Claude 3 Paid",
                "pricing": {"prompt": "0.000015", "completion": "0.000075"},
                "context_length": 200000,
            },
            {
                "id": "meta/llama-3-free-novision",
                "name": "",
                "pricing": {"prompt": "0"},
                "context_length": 4096,
            },
        ]
    }
    mock_client.get_response = MockResponse(status_code=200, json_data=mock_data)
    adapter = OpenRouterAdapter()

    models = await adapter.discover_models("some-key")

    assert len(models) == 3

    # Check gemini-2-free
    assert models[0].model_id == "google/gemini-2-free"
    assert models[0].display_name == "Gemini 2 Free"
    assert models[0].supports_vision is False
    assert models[0].context_length == 8192
    assert models[0].raw_metadata == mock_data["data"][0]

    # Check gpt-4-vision-free
    assert models[1].model_id == "openai/gpt-4-vision-free"
    assert models[1].display_name == "GPT-4 Vision Free"
    assert models[1].supports_vision is True
    assert models[1].context_length == 128000

    # Check llama-3-free-novision (which defaults to ID as display_name when empty)
    assert models[2].model_id == "meta/llama-3-free-novision"
    assert models[2].display_name == "meta/llama-3-free-novision"
    assert models[2].supports_vision is False
    assert models[2].context_length == 4096


async def test_discover_models_error_status(mock_client: MockAsyncClient) -> None:
    mock_client.get_response = MockResponse(status_code=500)
    adapter = OpenRouterAdapter()
    models = await adapter.discover_models("some-key")
    assert models == []


async def test_discover_models_exception(mock_client: MockAsyncClient) -> None:
    mock_client.get_response = httpx.ReadTimeout("Timeout")
    adapter = OpenRouterAdapter()
    models = await adapter.discover_models("some-key")
    assert models == []


async def test_discover_models_missing_key() -> None:
    adapter = OpenRouterAdapter()
    models = await adapter.discover_models(None)
    assert models == []


# --- Benchmark Tests -------------------------------------------------------------------

async def test_benchmark_success(mock_client: MockAsyncClient) -> None:
    mock_client.post_response = MockResponse(status_code=200)
    adapter = OpenRouterAdapter()

    with patch("time.perf_counter", side_effect=[0.0, 0.4]):  # 400ms -> speed_rating = 4
        result = await adapter.benchmark("some-model", "some-key")

    assert result.success is True
    assert result.model_id == "some-model"
    assert result.latency_ms == 400.0
    assert result.speed_rating == 4
    assert result.error is None


async def test_benchmark_failure(mock_client: MockAsyncClient) -> None:
    mock_client.post_response = MockResponse(status_code=400, text_content="Bad request")
    adapter = OpenRouterAdapter()

    with patch("time.perf_counter", side_effect=[0.0, 0.1]):
        result = await adapter.benchmark("some-model", "some-key")

    assert result.success is False
    assert result.model_id == "some-model"
    assert result.latency_ms == 100.0
    assert result.speed_rating is None
    assert result.error is not None
    assert "status 400" in result.error


async def test_benchmark_exception(mock_client: MockAsyncClient) -> None:
    mock_client.post_response = httpx.ConnectTimeout("Timeout")
    adapter = OpenRouterAdapter()

    with patch("time.perf_counter", side_effect=[0.0, 2.5]):  # 2500ms
        result = await adapter.benchmark("some-model", "some-key")

    assert result.success is False
    assert result.model_id == "some-model"
    assert result.latency_ms == 2500.0
    assert result.speed_rating is None
    assert result.error is not None
    assert "Timeout" in result.error


async def test_benchmark_missing_key() -> None:
    adapter = OpenRouterAdapter()
    result = await adapter.benchmark("some-model", None)
    assert result.success is False
    assert result.error == "API key is missing."


# --- Chat Tests ------------------------------------------------------------------------

async def test_chat_success(mock_client: MockAsyncClient) -> None:
    lines = [
        b'data: {"choices": [{"delta": {"content": "Hello"}, "finish_reason": null}]}',
        b'data: {"choices": [{"delta": {"content": " world"}, "finish_reason": null}]}',
        b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
        b'"usage": {"prompt_tokens": 10, "completion_tokens": 5}}',
        b"data: [DONE]",
    ]
    mock_client.stream_response = MockStreamResponse(status_code=200, lines=lines)
    adapter = OpenRouterAdapter()

    messages = [
        Message(role="system", content="You are helpful."),
        Message(
            role="user",
            content=[
                MessageContentPart(type="text", text="Hello"),
                MessageContentPart(type="image_url", image_url="https://example.com/img.png"),
            ],
        ),
    ]

    chunks = []
    async for chunk in await adapter.chat(
        messages, "some-model", api_key="some-key", temperature=0.7
    ):
        chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[0].delta == "Hello"
    assert chunks[0].finish_reason is None
    assert chunks[1].delta == " world"
    assert chunks[2].delta == ""
    assert chunks[2].finish_reason == "stop"
    assert chunks[2].tokens_in == 10
    assert chunks[2].tokens_out == 5

    # Verify formatting and payload details
    call = mock_client.calls[0]
    assert call[0] == "stream"
    assert call[1] == "POST"
    assert call[2] == "https://openrouter.ai/api/v1/chat/completions"
    payload = call[3]
    assert payload["model"] == "some-model"
    assert payload["temperature"] == 0.7
    assert payload["stream"] is True
    assert len(payload["messages"]) == 2
    assert payload["messages"][0] == {"role": "system", "content": "You are helpful."}
    assert payload["messages"][1]["role"] == "user"
    assert payload["messages"][1]["content"] == [
        {"type": "text", "text": "Hello"},
        {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
    ]


async def test_chat_error_status(mock_client: MockAsyncClient) -> None:
    mock_client.stream_response = MockStreamResponse(
        status_code=500, error_text="Internal server error"
    )
    adapter = OpenRouterAdapter()

    messages = [Message(role="user", content="Hi")]

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        stream = await adapter.chat(messages, "some-model", api_key="some-key")
        async for _ in stream:
            pass

    assert exc_info.value.response.status_code == 500
    assert "Internal server error" in str(exc_info.value)


async def test_chat_rate_limit(mock_client: MockAsyncClient) -> None:
    mock_client.stream_response = MockStreamResponse(
        status_code=429, error_text="Rate limit exceeded"
    )
    adapter = OpenRouterAdapter()

    messages = [Message(role="user", content="Hi")]

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        stream = await adapter.chat(messages, "some-model", api_key="some-key")
        async for _ in stream:
            pass

    assert exc_info.value.response.status_code == 429
    assert "Rate limit exceeded" in str(exc_info.value)


async def test_chat_missing_key() -> None:
    adapter = OpenRouterAdapter()
    messages = [Message(role="user", content="Hi")]
    with pytest.raises(ValueError) as exc_info:
        await adapter.chat(messages, "some-model")
    assert "API key is required" in str(exc_info.value)


# --- Image Generation Tests -------------------------------------------------------------

async def test_generate_image_unsupported() -> None:
    adapter = OpenRouterAdapter()
    with pytest.raises(NotImplementedError) as exc_info:
        await adapter.generate_image("A cute cat")
    assert "does not support image generation" in str(exc_info.value)


# --- Health Check Tests -----------------------------------------------------------------

async def test_health_check_healthy(mock_client: MockAsyncClient) -> None:
    mock_client.get_response = MockResponse(status_code=200)
    adapter = OpenRouterAdapter()

    status = await adapter.health_check()

    assert status.healthy is True
    assert status.latency_ms is not None
    assert status.detail is not None
    assert "Status: 200" in status.detail


async def test_health_check_unhealthy(mock_client: MockAsyncClient) -> None:
    mock_client.get_response = MockResponse(status_code=503)
    adapter = OpenRouterAdapter()

    status = await adapter.health_check()

    assert status.healthy is False
    assert status.detail is not None
    assert "server error: 503" in status.detail


async def test_health_check_exception(mock_client: MockAsyncClient) -> None:
    mock_client.get_response = httpx.ConnectError("Connection error")
    adapter = OpenRouterAdapter()

    status = await adapter.health_check()

    assert status.healthy is False
    assert status.detail is not None
    assert "Connection error" in status.detail


# --- Quota Tests -----------------------------------------------------------------------

def test_remaining_quota_default() -> None:
    adapter = OpenRouterAdapter()
    usage = QuotaUsage(
        provider_name="openrouter", date=date(2026, 7, 15), request_count=10, daily_limit=None
    )
    status = adapter.remaining_quota(usage)
    assert status.limit == 50
    assert status.remaining == 40
    assert status.exhausted is False
    assert status.reset_at == datetime(2026, 7, 16, 0, 0, tzinfo=UTC)


def test_remaining_quota_custom() -> None:
    adapter = OpenRouterAdapter()
    usage = QuotaUsage(
        provider_name="openrouter", date=date(2026, 7, 15), request_count=8, daily_limit=20
    )
    status = adapter.remaining_quota(usage)
    assert status.limit == 20
    assert status.remaining == 12
    assert status.exhausted is False


def test_remaining_quota_exhausted() -> None:
    adapter = OpenRouterAdapter()
    usage = QuotaUsage(
        provider_name="openrouter", date=date(2026, 7, 15), request_count=50, daily_limit=50
    )
    status = adapter.remaining_quota(usage)
    assert status.remaining == 0
    assert status.exhausted is True
