"""End-to-end: a real adapter (Groq) through the full HTTP -> routing ->
streaming stack. Only the provider's actual HTTP call is mocked (matching
the pattern used in tests/providers/test_groq.py) — the adapter itself,
the routing engine, key decryption, and the API layer all run for real.

The request's "model" is a specific model_id here (not "auto:*"), so it
also exercises the Model Registry lookup: a Model row for
"llama-3.3-70b-versatile" under "groq" must exist for it to be routed to.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from tests.conftest import AddProviderKey, MakeUser, OnlyProvidersEnabled, SeedModel


async def _mock_aiter_lines() -> AsyncIterator[str]:
    yield 'data: {"choices": [{"delta": {"content": "Hello"}, "finish_reason": null}]}'
    yield (
        'data: {"choices": [{"delta": {"content": " world!"}, "finish_reason": "stop"}], '
        '"usage": {"prompt_tokens": 8, "completion_tokens": 3}}'
    )
    yield "data: [DONE]"


def test_chat_completion_through_real_groq_adapter(
    client: TestClient,
    make_user: MakeUser,
    add_provider_key: AddProviderKey,
    only_providers_enabled: OnlyProvidersEnabled,
    seed_model: SeedModel,
) -> None:
    only_providers_enabled({"groq"})
    add_provider_key("groq", "sk-real-test-key", is_shared=True)
    seed_model("groq", "llama-3.3-70b-versatile")
    _, token = make_user("chat-integration@example.com")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.aiter_lines = _mock_aiter_lines

    mock_stream = AsyncMock()
    mock_stream.__aenter__.return_value = mock_response

    with patch("httpx.AsyncClient.stream") as mock_stream_method:
        mock_stream_method.return_value = mock_stream

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "Hi there"}],
                "stream": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        # the mock is still active here, so it's safe to inspect the call
        # the real GroqAdapter made with our decrypted shared key
        _, call_kwargs = mock_stream_method.call_args
        assert call_kwargs["headers"]["Authorization"] == "Bearer sk-real-test-key"

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_name"] == "groq"
    assert body["model_id"] == "llama-3.3-70b-versatile"
    assert body["model"] == "llama-3.3-70b-versatile"
    assert body["choices"][0]["message"]["content"] == "Hello world!"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"] == {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11}


def test_chat_completion_streams_sse_through_real_groq_adapter(
    client: TestClient,
    make_user: MakeUser,
    add_provider_key: AddProviderKey,
    only_providers_enabled: OnlyProvidersEnabled,
    seed_model: SeedModel,
) -> None:
    only_providers_enabled({"groq"})
    add_provider_key("groq", "sk-real-test-key", is_shared=True)
    seed_model("groq", "llama-3.3-70b-versatile")
    _, token = make_user("chat-integration-stream@example.com")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.aiter_lines = _mock_aiter_lines

    mock_stream = AsyncMock()
    mock_stream.__aenter__.return_value = mock_response

    with patch("httpx.AsyncClient.stream") as mock_stream_method:
        mock_stream_method.return_value = mock_stream

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "Hi there"}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "Hello" in resp.text
    assert "world!" in resp.text
    assert resp.text.strip().endswith("data: [DONE]")
