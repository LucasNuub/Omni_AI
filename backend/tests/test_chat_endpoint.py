from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.providers.base import ChatChunk, Message
from app.providers.registry import ADAPTERS
from tests.conftest import AddProviderKey, MakeUser, OnlyProvidersEnabled, SeedModel
from tests.fakes import FakeAdapter


def _parse_sse(text: str) -> list[dict[str, Any]]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.startswith("data: "):
            continue
        payload = block[len("data: ") :]
        if payload == "[DONE]":
            continue
        events.append(json.loads(payload))
    return events


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_chat_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/chat/completions", json={"model": "x", "messages": []})
    assert resp.status_code == 401


def test_chat_streams_sse_from_first_available_provider(
    client: TestClient,
    make_user: MakeUser,
    only_providers_enabled: OnlyProvidersEnabled,
    seed_model: SeedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only_providers_enabled({"pollinations"})
    seed_model("pollinations", "stream-test-model")
    monkeypatch.setitem(
        ADAPTERS,
        "pollinations",
        FakeAdapter(
            name="pollinations",
            chat_chunks=[
                ChatChunk(delta="Hello"),
                ChatChunk(delta=" world", finish_reason="stop", tokens_in=3, tokens_out=2),
            ],
        ),
    )
    _, token = make_user("chat-stream@example.com")

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto:balanced", "messages": [{"role": "user", "content": "hi"}]},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    assert [e["choices"][0]["delta"]["content"] for e in events] == ["Hello", " world"]
    assert events[-1]["choices"][0]["finish_reason"] == "stop"
    assert all(e["model"] == "stream-test-model" for e in events)
    assert all(e["provider_name"] == "pollinations" for e in events)


def test_chat_non_streaming_aggregates_full_response(
    client: TestClient,
    make_user: MakeUser,
    only_providers_enabled: OnlyProvidersEnabled,
    seed_model: SeedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only_providers_enabled({"pollinations"})
    seed_model("pollinations", "aggregate-test-model")
    monkeypatch.setitem(
        ADAPTERS,
        "pollinations",
        FakeAdapter(
            name="pollinations",
            chat_chunks=[
                ChatChunk(delta="Hel"),
                ChatChunk(delta="lo", finish_reason="stop", tokens_in=5, tokens_out=2),
            ],
        ),
    )
    _, token = make_user("chat-nonstream@example.com")

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto:balanced",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["provider_name"] == "pollinations"
    assert body["model_id"] == "aggregate-test-model"
    assert body["model"] == "aggregate-test-model"
    assert body["choices"][0]["message"]["content"] == "Hello"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"] == {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}


def test_chat_falls_back_to_next_provider_on_failure(
    client: TestClient,
    make_user: MakeUser,
    add_provider_key: AddProviderKey,
    only_providers_enabled: OnlyProvidersEnabled,
    seed_model: SeedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only_providers_enabled({"groq", "pollinations"})
    add_provider_key("groq", "sk-fallback-test", is_shared=True)
    seed_model("groq", "fallback-groq-model")
    seed_model("pollinations", "fallback-poll-model")
    monkeypatch.setitem(
        ADAPTERS, "groq", FakeAdapter(name="groq", auth_type="api_key", fail_immediately=True)
    )
    fallback_chunks = [ChatChunk(delta="fallback", finish_reason="stop")]
    monkeypatch.setitem(
        ADAPTERS, "pollinations", FakeAdapter(name="pollinations", chat_chunks=fallback_chunks)
    )
    _, token = make_user("chat-fallback@example.com")

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto:balanced",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_name"] == "pollinations"
    assert body["model_id"] == "fallback-poll-model"
    assert body["choices"][0]["message"]["content"] == "fallback"


def test_chat_returns_normalized_error_when_all_providers_fail(
    client: TestClient,
    make_user: MakeUser,
    add_provider_key: AddProviderKey,
    only_providers_enabled: OnlyProvidersEnabled,
    seed_model: SeedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only_providers_enabled({"groq", "pollinations"})
    add_provider_key("groq", "sk-allfail-test", is_shared=True)
    seed_model("groq", "allfail-groq-model")
    seed_model("pollinations", "allfail-poll-model")
    monkeypatch.setitem(
        ADAPTERS, "groq", FakeAdapter(name="groq", auth_type="api_key", fail_immediately=True)
    )
    monkeypatch.setitem(
        ADAPTERS, "pollinations", FakeAdapter(name="pollinations", fail_immediately=True)
    )
    _, token = make_user("chat-allfail@example.com")

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto:balanced", "messages": [{"role": "user", "content": "hi"}]},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 503
    body = resp.json()
    assert "detail" in body
    # never leak the raw underlying exception text to the client
    assert "unavailable" in body["detail"].lower()
    assert "RuntimeError" not in body["detail"]


def test_chat_returns_normalized_error_when_no_providers_enabled(
    client: TestClient,
    make_user: MakeUser,
    only_providers_enabled: OnlyProvidersEnabled,
) -> None:
    only_providers_enabled(set())
    _, token = make_user("chat-noproviders@example.com")

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto:balanced", "messages": [{"role": "user", "content": "hi"}]},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 503


def test_chat_skips_api_key_provider_with_no_key_configured(
    client: TestClient,
    make_user: MakeUser,
    only_providers_enabled: OnlyProvidersEnabled,
    seed_model: SeedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """huggingface needs a key and has none configured; pollinations needs none.

    Uses huggingface rather than groq here specifically because no other
    test in this module ever gives groq a *shared* key — this test would be
    order-dependent (and wrong) if it ran after one that did.
    """
    only_providers_enabled({"huggingface", "pollinations"})
    seed_model("huggingface", "nokey-hf-model")
    seed_model("pollinations", "nokey-poll-model")
    huggingface_fake = FakeAdapter(name="huggingface", auth_type="api_key")
    monkeypatch.setitem(ADAPTERS, "huggingface", huggingface_fake)
    monkeypatch.setitem(
        ADAPTERS,
        "pollinations",
        FakeAdapter(name="pollinations", chat_chunks=[ChatChunk(delta="ok", finish_reason="stop")]),
    )
    _, token = make_user("chat-nokey@example.com")

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto:balanced",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_name"] == "pollinations"
    assert body["model_id"] == "nokey-poll-model"


def test_chat_uses_shared_provider_key_when_available(
    client: TestClient,
    make_user: MakeUser,
    add_provider_key: AddProviderKey,
    only_providers_enabled: OnlyProvidersEnabled,
    seed_model: SeedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only_providers_enabled({"groq"})
    add_provider_key("groq", "sk-shared-test-key", is_shared=True)
    seed_model("groq", "sharedkey-groq-model")

    captured_kwargs: dict[str, Any] = {}

    class _KeyCapturingAdapter(FakeAdapter):
        async def chat(
            self, messages: list[Message], model_id: str, **kwargs: Any
        ) -> AsyncIterator[ChatChunk]:
            captured_kwargs.update(kwargs)
            async for chunk in super().chat(messages, model_id, **kwargs):
                yield chunk

    monkeypatch.setitem(
        ADAPTERS,
        "groq",
        _KeyCapturingAdapter(
            name="groq",
            auth_type="api_key",
            chat_chunks=[ChatChunk(delta="ok", finish_reason="stop")],
        ),
    )
    _, token = make_user("chat-sharedkey@example.com")

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "sharedkey-groq-model",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    assert resp.json()["model_id"] == "sharedkey-groq-model"
    assert captured_kwargs.get("api_key") == "sk-shared-test-key"


# --- "model" field resolution: auto:* profiles, specific model_id, 400 -------------------


def test_chat_unknown_auto_profile_returns_400(
    client: TestClient,
    make_user: MakeUser,
    only_providers_enabled: OnlyProvidersEnabled,
    seed_model: SeedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only_providers_enabled({"pollinations"})
    seed_model("pollinations", "profile-400-model")
    monkeypatch.setitem(ADAPTERS, "pollinations", FakeAdapter(name="pollinations"))
    _, token = make_user("chat-badprofile@example.com")

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto:cheapest", "messages": [{"role": "user", "content": "hi"}]},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "auto:cheapest" in detail
    assert "auto:fast" in detail
    assert "auto:balanced" in detail
    assert "auto:best" in detail


def test_chat_specific_model_id_falls_back_across_providers(
    client: TestClient,
    make_user: MakeUser,
    add_provider_key: AddProviderKey,
    only_providers_enabled: OnlyProvidersEnabled,
    seed_model: SeedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same model_id enabled on two providers still gets provider fallback."""
    only_providers_enabled({"groq", "pollinations"})
    add_provider_key("groq", "sk-specific-model-test", is_shared=True)
    seed_model("groq", "shared-model-x")
    seed_model("pollinations", "shared-model-x")
    monkeypatch.setitem(
        ADAPTERS, "groq", FakeAdapter(name="groq", auth_type="api_key", fail_immediately=True)
    )
    monkeypatch.setitem(
        ADAPTERS,
        "pollinations",
        FakeAdapter(name="pollinations", chat_chunks=[ChatChunk(delta="ok", finish_reason="stop")]),
    )
    _, token = make_user("chat-specificmodel@example.com")

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "shared-model-x",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_name"] == "pollinations"
    assert body["model_id"] == "shared-model-x"


def test_chat_required_capability_filters_candidates(
    client: TestClient,
    make_user: MakeUser,
    only_providers_enabled: OnlyProvidersEnabled,
    seed_model: SeedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only_providers_enabled({"pollinations"})
    seed_model("pollinations", "cap-model-no-vision", supports_vision=False)
    seed_model("pollinations", "cap-model-has-vision", supports_vision=True)
    monkeypatch.setitem(
        ADAPTERS,
        "pollinations",
        FakeAdapter(name="pollinations", chat_chunks=[ChatChunk(delta="ok", finish_reason="stop")]),
    )
    _, token = make_user("chat-capability@example.com")

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto:balanced",
            "required_capability": "vision",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    assert resp.json()["model_id"] == "cap-model-has-vision"
