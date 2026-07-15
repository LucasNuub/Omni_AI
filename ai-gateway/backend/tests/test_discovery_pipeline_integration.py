"""Full discovery pipeline, end to end — see SPEC.md section 9.

Per the task: validate_key and discover_models are called for real against
Pollinations (hosted, reachable) and Ollama (local, safe even when nothing
is listening — its adapter degrades to an empty model list rather than
raising, which becomes a genuine "no models found" pipeline failure here,
not a simulated one). The API-key-gated adapter (Groq) is exercised with
its actual HTTP calls mocked, same convention as tests/providers/test_groq.py.

Only the benchmark step is mocked for the real-Pollinations run, to avoid
depending on the timing/availability of a real chat completion for a
deterministic test — validate_key and discover_models still hit the real
network.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HealthStatus as DbHealthStatus
from app.db.models import Model as ModelRow
from app.db.models import ProviderKey as ProviderKeyRow
from app.db.models import ProviderKeyStatus
from app.discovery.scanner import (
    DiscoveryOutcome,
    DiscoveryStepName,
    DiscoveryStepStatus,
    run_discovery_pipeline,
)
from app.providers.base import ProviderAdapter
from app.providers.groq import GroqAdapter
from app.providers.ollama import OllamaAdapter
from app.providers.pollinations import PollinationsAdapter


async def _make_key(db_session: AsyncSession, provider_name: str) -> ProviderKeyRow:
    key = ProviderKeyRow(
        user_id=None,
        provider_name=provider_name,
        encrypted_key="unused-in-these-tests",
        is_shared=True,
        status=ProviderKeyStatus.pending,
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)
    return key


async def _saved_models(db_session: AsyncSession, provider_name: str) -> list[ModelRow]:
    result = await db_session.execute(
        select(ModelRow).where(ModelRow.provider_name == provider_name)
    )
    return list(result.scalars().all())


# --- real Pollinations: validate_key + discover_models are genuinely live -----------------


async def test_real_pollinations_validate_key_and_discover_models() -> None:
    """No mocking at all — a real network round trip, as the task asks for."""
    adapter = PollinationsAdapter()

    assert await adapter.validate_key(None) is True

    models = await adapter.discover_models(None)
    assert len(models) > 0
    assert all(m.model_id for m in models)


async def test_pipeline_end_to_end_real_pollinations(db_session: AsyncSession) -> None:
    key = await _make_key(db_session, "pollinations")
    # PollinationsAdapter satisfies ProviderAdapter structurally (it doesn't
    # inherit it) but mypy's structural check trips on chat()'s async
    # generator vs. coroutine ambiguity, same as app/providers/registry.py.
    adapter = cast(ProviderAdapter, PollinationsAdapter())

    async def _mock_aiter_lines() -> AsyncIterator[str]:
        yield 'data: {"choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}]}'
        yield "data: [DONE]"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.aiter_lines = _mock_aiter_lines
    mock_stream = AsyncMock()
    mock_stream.__aenter__.return_value = mock_response

    with patch("httpx.AsyncClient.stream") as mock_stream_method:
        mock_stream_method.return_value = mock_stream
        progress = await run_discovery_pipeline(
            db_session, key, adapter, None, benchmark_sample_size=2
        )

    assert progress.outcome == DiscoveryOutcome.success
    assert progress.models_added > 0

    await db_session.refresh(key)
    assert key.status == ProviderKeyStatus.active
    assert key.health_status == DbHealthStatus.green

    saved = await _saved_models(db_session, "pollinations")
    # >= rather than ==: other tests in the suite also seed "pollinations"
    # Model rows against this same persistent test DB (chat endpoint tests
    # via the seed_model fixture); this just confirms the real discovery
    # results actually landed, not that they're the only rows present.
    assert len(saved) >= progress.models_added
    # the two models actually sent through the mocked benchmark call got a rating
    benchmarked = [m for m in saved if m.speed_rating is not None]
    assert len(benchmarked) == 2


# --- real Ollama: unreachable locally -> genuine "no models found" ------------------------


async def test_real_ollama_discover_models_degrades_gracefully_when_unreachable() -> None:
    """No mocking — exercises the adapter's real (documented) fallback to []."""
    adapter = OllamaAdapter()

    assert await adapter.validate_key(None) is True  # Ollama never needs a key
    models = await adapter.discover_models(None)
    assert models == []  # genuinely unreachable in this environment


async def test_pipeline_end_to_end_real_ollama_reports_no_models_found(
    db_session: AsyncSession,
) -> None:
    key = await _make_key(db_session, "ollama")
    adapter = OllamaAdapter()

    progress = await run_discovery_pipeline(db_session, key, adapter, None)

    assert progress.outcome == DiscoveryOutcome.error
    assert progress.error is not None
    assert "no models" in progress.error.lower()
    assert progress.steps[DiscoveryStepName.discovering_models] == DiscoveryStepStatus.failed

    await db_session.refresh(key)
    assert key.status == ProviderKeyStatus.pending  # untouched — nothing to persist as active

    saved = await _saved_models(db_session, "ollama")
    assert saved == []


# --- API-key-gated provider (Groq): HTTP mocked, adapter itself is real -------------------


async def test_pipeline_end_to_end_mocked_groq_invalid_key(db_session: AsyncSession) -> None:
    key = await _make_key(db_session, "groq")
    adapter = GroqAdapter()
    # Other tests in this module also save "groq" models to the same
    # persistent test DB, so assert against the *delta*, not an absolute
    # empty list, to stay independent of execution order.
    models_before = len(await _saved_models(db_session, "groq"))

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(401, json={"error": "invalid api key"})
        progress = await run_discovery_pipeline(db_session, key, adapter, "sk-bad-key")

    assert progress.outcome == DiscoveryOutcome.invalid_key
    await db_session.refresh(key)
    assert key.status == ProviderKeyStatus.invalid_key
    assert len(await _saved_models(db_session, "groq")) == models_before


async def test_pipeline_end_to_end_mocked_groq_full_success(db_session: AsyncSession) -> None:
    key = await _make_key(db_session, "groq")
    adapter = GroqAdapter()

    models_payload = {
        "data": [
            {"id": "llama-3.3-70b-versatile", "context_window": 131072},
            {"id": "totally-unknown-model-xyz"},
        ]
    }
    # GroqAdapter.benchmark uses a plain client.post(...), not client.stream(...)
    # (only .chat() streams) — mock accordingly, matching tests/providers/test_groq.py.
    chat_completion_payload = {"choices": [{"message": {"content": "OK"}}]}

    with (
        patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_get.return_value = httpx.Response(200, json=models_payload)
        mock_post.return_value = httpx.Response(200, json=chat_completion_payload)

        progress = await run_discovery_pipeline(db_session, key, adapter, "sk-valid-key")

    assert progress.outcome == DiscoveryOutcome.success
    assert progress.models_added == 2

    await db_session.refresh(key)
    assert key.status == ProviderKeyStatus.active
    assert key.health_status == DbHealthStatus.green

    saved = {m.model_id: m for m in await _saved_models(db_session, "groq")}
    assert saved["llama-3.3-70b-versatile"].quality_source.value == "curated"
    assert saved["llama-3.3-70b-versatile"].supports_coding_hint is not None
    assert saved["llama-3.3-70b-versatile"].speed_rating is not None
    assert saved["totally-unknown-model-xyz"].quality_source.value == "unrated"
    assert saved["totally-unknown-model-xyz"].supports_coding_hint is None


async def test_rescan_upserts_existing_model_rows_instead_of_duplicating(
    db_session: AsyncSession,
) -> None:
    key = await _make_key(db_session, "groq")
    adapter = GroqAdapter()
    # A model id unique to this test — other tests in this module also save
    # "groq" models under a shared, persistent test DB, so filtering by
    # provider_name alone would pick up their rows too.
    unique_model_id = "rescan-upsert-test-model"

    async def _run_with_one_model(context_window: int) -> Any:
        payload = {
            "data": [{"id": unique_model_id, "context_window": context_window}]
        }
        chat_completion_payload = {"choices": [{"message": {"content": "OK"}}]}

        with (
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
            patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
        ):
            mock_get.return_value = httpx.Response(200, json=payload)
            mock_post.return_value = httpx.Response(200, json=chat_completion_payload)
            return await run_discovery_pipeline(db_session, key, adapter, "sk-valid-key")

    first = await _run_with_one_model(131072)
    assert first.models_added == 1

    second = await _run_with_one_model(999999)  # provider "changed" the context length
    assert second.models_added == 1

    saved = [m for m in await _saved_models(db_session, "groq") if m.model_id == unique_model_id]
    assert len(saved) == 1  # upserted, not duplicated
    assert saved[0].context_length == 999999
