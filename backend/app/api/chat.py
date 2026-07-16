"""OpenAI-compatible chat completions — see SPEC.md sections 7, 8, and 12.

Resolution now happens at the **model** level via the Model Registry
(``router/engine.py``'s ``route_by_model``), not provider level: candidates
are built from enabled ``Model`` rows joined with their ``Provider`` (for
priority/enabled) and ``ProviderKey`` (for the usable key, health, and
today's quota). The request's ``model`` field selects how those candidates
get ranked:

- ``"auto:fast"`` / ``"auto:balanced"`` (default profile) / ``"auto:best"``
  — rank every enabled model via the matching ``RoutingProfile``, optionally
  narrowed by the request's ``required_capability``.
- any other value is treated as a literal ``model_id`` — candidates are
  restricted to that id (which may exist on more than one provider, still
  giving provider-level fallback), routed with the balanced profile and no
  capability filter (the caller already picked an exact model).
- an ``"auto:"``-prefixed value that isn't one of the three known profiles
  is a 400, not a silent fallback.

Streaming a fallback chain is the tricky part: once the client has started
receiving SSE bytes, the router can no longer switch providers without
corrupting the response. So each candidate's connection is "primed" —
the adapter's async generator is opened and its first chunk fetched — all
inside :meth:`RoutingEngine.route`, where failures still trigger retry and
fallback. Only after priming succeeds does this module start actually
streaming to the client; a failure from that point on just ends the
stream, it can't silently swap providers underneath an in-flight response.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.auth import get_current_user
from app.core.config import Settings, get_settings
from app.core.security import DecryptionError, decrypt_key
from app.db.models import AuthType, Provider, ProviderKeyStatus, User
from app.db.models import HealthStatus as DbHealthStatus
from app.db.models import Model as ModelRow
from app.db.models import ProviderKey as ProviderKeyRow
from app.db.models import QuotaUsage as QuotaUsageRow
from app.db.session import get_db
from app.providers.base import ChatChunk, Message, ProviderAdapter
from app.providers.base import QuotaUsage as QuotaUsageSnapshot
from app.providers.registry import ADAPTERS
from app.router.engine import (
    AllProvidersExhaustedError,
    ModelCandidate,
    RequiredCapability,
    RoutingEngine,
    RoutingProfile,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["chat"])

_NORMALIZED_UPSTREAM_ERROR = (
    "All providers are currently unavailable. Please try again shortly."
)

_AUTO_PROFILES: dict[str, RoutingProfile] = {
    "fast": RoutingProfile.fast,
    "balanced": RoutingProfile.balanced,
    "best": RoutingProfile.best_quality,
}

# Fields the gateway itself consumes (routing hints, not completion params).
# ChatCompletionRequest's extra="allow" exists so pass-through completion
# kwargs (temperature, max_tokens, ...) reach the provider verbatim — see
# GroqAdapter.chat's payload.update(kwargs). But this is a gateway boundary:
# a field the *client* sends for the gateway's own use must never leak into
# the outbound provider request just because it landed in model_extra.
_GATEWAY_ONLY_EXTRA_FIELDS = frozenset({"profile", "required_capability"})


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[Message]
    stream: bool = True
    required_capability: RequiredCapability | None = None


class ChatCompletionMessageOut(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatCompletionMessageOut
    finish_reason: str | None = None


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    # Non-standard extras (SPEC.md section 8): which model actually served
    # the request, since ``model`` may have been "auto:*" in the request.
    provider_name: str
    model_id: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage | None = None


@dataclass
class _PrimedStream:
    first_chunk: ChatChunk
    rest: AsyncIterator[ChatChunk]


def get_routing_engine(request: Request) -> RoutingEngine:
    return request.app.state.routing_engine  # type: ignore[no-any-return]


async def _resolve_api_key_row(
    db: AsyncSession, provider_name: str, user: User
) -> ProviderKeyRow | None:
    """Prefer the requesting user's own active key, then the shared pool's.

    Nothing in the schema stops more than one active key existing for the
    same provider/user (e.g. two shared keys added for extra headroom), so
    ties are broken by most-recently-added rather than assuming uniqueness.
    """
    result = await db.execute(
        select(ProviderKeyRow)
        .where(
            ProviderKeyRow.provider_name == provider_name,
            ProviderKeyRow.status == ProviderKeyStatus.active,
            ProviderKeyRow.user_id == user.id,
        )
        .order_by(ProviderKeyRow.added_at.desc())
    )
    key_row = result.scalars().first()

    if key_row is None:
        result = await db.execute(
            select(ProviderKeyRow)
            .where(
                ProviderKeyRow.provider_name == provider_name,
                ProviderKeyRow.status == ProviderKeyStatus.active,
                ProviderKeyRow.is_shared.is_(True),
                ProviderKeyRow.user_id.is_(None),
            )
            .order_by(ProviderKeyRow.added_at.desc())
        )
        key_row = result.scalars().first()

    return key_row


def _decrypt_or_none(key_row: ProviderKeyRow, settings: Settings) -> str | None:
    try:
        return decrypt_key(key_row.encrypted_key, settings.master_encryption_key)
    except DecryptionError:
        logger.error("failed to decrypt stored key for provider %s", key_row.provider_name)
        return None


async def _quota_snapshot(
    db: AsyncSession, provider_name: str, quota_user_id: int | None, today: date
) -> QuotaUsageSnapshot:
    stmt = select(QuotaUsageRow).where(
        QuotaUsageRow.provider_name == provider_name, QuotaUsageRow.date == today
    )
    stmt = (
        stmt.where(QuotaUsageRow.user_id.is_(None))
        if quota_user_id is None
        else stmt.where(QuotaUsageRow.user_id == quota_user_id)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return QuotaUsageSnapshot(provider_name=provider_name, date=today, request_count=0)
    return QuotaUsageSnapshot(
        provider_name=provider_name,
        date=row.date,
        request_count=row.request_count,
        daily_limit=row.daily_limit,
    )


@dataclass(frozen=True)
class _ProviderContext:
    api_key: str | None
    usable: bool


async def _resolve_provider_context(
    db: AsyncSession,
    provider: Provider,
    adapter: ProviderAdapter,
    user: User,
    settings: Settings,
    today: date,
) -> _ProviderContext:
    """Resolve a usable key (if needed) and check health/quota, once per provider.

    "joined with their ProviderKey health/quota" (SPEC.md section 8): an
    ``api_key``-auth provider needs an active key that isn't marked red, and
    every provider (key or not) needs unexhausted quota for today's shared
    or personal usage row, matching the same check ``/status`` uses.
    """
    api_key: str | None = None
    quota_user_id: int | None = None

    if provider.auth_type == AuthType.api_key:
        key_row = await _resolve_api_key_row(db, provider.name, user)
        if key_row is None or key_row.health_status == DbHealthStatus.red:
            return _ProviderContext(api_key=None, usable=False)
        api_key = _decrypt_or_none(key_row, settings)
        if api_key is None:
            return _ProviderContext(api_key=None, usable=False)
        quota_user_id = key_row.user_id

    usage = await _quota_snapshot(db, provider.name, quota_user_id, today)
    if adapter.remaining_quota(usage).exhausted:
        return _ProviderContext(api_key=api_key, usable=False)

    return _ProviderContext(api_key=api_key, usable=True)


async def _build_model_candidates(
    db: AsyncSession, user: User, settings: Settings
) -> tuple[list[ModelCandidate], dict[str, str | None]]:
    """Query enabled Model rows joined with their Provider, resolving each
    distinct provider's key/health/quota once (models routinely share a
    provider). Returns the candidates plus a provider_name -> api_key map
    for building invoke callables later.
    """
    result = await db.execute(
        select(ModelRow, Provider)
        .join(Provider, ModelRow.provider_name == Provider.name)
        .where(ModelRow.enabled.is_(True), Provider.enabled.is_(True))
        .order_by(Provider.priority, ModelRow.model_id)
    )
    rows = result.all()

    today = date.today()
    contexts: dict[str, _ProviderContext] = {}
    candidates: list[ModelCandidate] = []

    for model_row, provider_row in rows:
        adapter = ADAPTERS.get(provider_row.name)
        if adapter is None:
            continue

        if provider_row.name not in contexts:
            contexts[provider_row.name] = await _resolve_provider_context(
                db, provider_row, adapter, user, settings, today
            )
        context = contexts[provider_row.name]
        if not context.usable:
            continue

        candidates.append(
            ModelCandidate(
                provider_name=provider_row.name,
                provider_priority=provider_row.priority,
                model_id=model_row.model_id,
                speed_rating=model_row.speed_rating,
                supports_vision=model_row.supports_vision,
                supports_coding_hint=model_row.supports_coding_hint,
                supports_reasoning_hint=model_row.supports_reasoning_hint,
            )
        )

    api_keys = {name: ctx.api_key for name, ctx in contexts.items()}
    return candidates, api_keys


def _select_profile_and_candidates(
    body: ChatCompletionRequest, all_candidates: list[ModelCandidate]
) -> tuple[list[ModelCandidate], RoutingProfile, RequiredCapability | None]:
    """Interpret the request's ``model`` field: an "auto:<profile>" name, or
    a literal model_id to restrict candidates to (still provider-fallback-able).
    """
    if body.model.startswith("auto:"):
        profile_name = body.model.removeprefix("auto:")
        profile = _AUTO_PROFILES.get(profile_name)
        if profile is None:
            valid = ", ".join(f"auto:{name}" for name in _AUTO_PROFILES)
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unknown routing profile '{body.model}'. Valid values: {valid}, "
                "or a specific model id.",
            )
        return all_candidates, profile, body.required_capability

    matching = [c for c in all_candidates if c.model_id == body.model]
    return matching, RoutingProfile.balanced, None


def _make_invoke(
    adapter: ProviderAdapter,
    messages: list[Message],
    model_id: str,
    api_key: str | None,
    extra_kwargs: dict[str, Any],
) -> Callable[[], Awaitable[_PrimedStream]]:
    async def _invoke() -> _PrimedStream:
        kwargs: dict[str, Any] = dict(extra_kwargs)
        if api_key:
            kwargs["api_key"] = api_key
        # ProviderAdapter.chat is declared `async def ... -> AsyncIterator[ChatChunk]`,
        # which mypy reads as "coroutine returning an iterator" — but every real
        # implementation is an async generator (`yield`-based), callable directly
        # without awaiting. The cast reflects actual adapter behavior, not base.py's
        # (out of scope here) declaration.
        agen = cast("AsyncIterator[ChatChunk]", adapter.chat(messages, model_id, **kwargs))
        first_chunk = await agen.__anext__()
        return _PrimedStream(first_chunk=first_chunk, rest=agen)

    return _invoke


def _make_invoke_factory(
    messages: list[Message],
    extra_kwargs: dict[str, Any],
    api_keys: dict[str, str | None],
) -> Callable[[ModelCandidate], Callable[[], Awaitable[_PrimedStream]]]:
    def _for_candidate(candidate: ModelCandidate) -> Callable[[], Awaitable[_PrimedStream]]:
        adapter = ADAPTERS[candidate.provider_name]
        api_key = api_keys.get(candidate.provider_name)
        return _make_invoke(adapter, messages, candidate.model_id, api_key, extra_kwargs)

    return _for_candidate


def _sse_event(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


def _chunk_payload(
    completion_id: str, created: int, provider_name: str, model_id: str, chunk: ChatChunk
) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_id,
        "provider_name": provider_name,
        "model_id": model_id,
        "choices": [
            {
                "index": 0,
                "delta": {"content": chunk.delta},
                "finish_reason": chunk.finish_reason,
            }
        ],
    }


async def _stream_sse(
    primed: _PrimedStream, completion_id: str, created: int, provider_name: str, model_id: str
) -> AsyncIterator[bytes]:
    yield _sse_event(
        _chunk_payload(completion_id, created, provider_name, model_id, primed.first_chunk)
    )
    try:
        async for chunk in primed.rest:
            yield _sse_event(_chunk_payload(completion_id, created, provider_name, model_id, chunk))
    except Exception as exc:  # noqa: BLE001 - normalized at the boundary
        logger.warning("provider %s failed mid-stream: %s", provider_name, exc)
        error_payload = {"message": _NORMALIZED_UPSTREAM_ERROR, "type": "upstream_error"}
        yield _sse_event({"error": error_payload})
    yield b"data: [DONE]\n\n"


async def _aggregate(primed: _PrimedStream) -> tuple[str, str | None, int | None, int | None]:
    """Consume the whole primed stream and collapse it into one response.

    Nothing has been sent to the client yet at this point, so a failure here
    can still surface as a clean HTTP error instead of a broken stream.
    """
    parts = [primed.first_chunk.delta]
    finish_reason = primed.first_chunk.finish_reason
    tokens_in = primed.first_chunk.tokens_in
    tokens_out = primed.first_chunk.tokens_out

    async for chunk in primed.rest:
        parts.append(chunk.delta)
        if chunk.finish_reason is not None:
            finish_reason = chunk.finish_reason
        if chunk.tokens_in is not None:
            tokens_in = chunk.tokens_in
        if chunk.tokens_out is not None:
            tokens_out = chunk.tokens_out

    return "".join(parts), finish_reason, tokens_in, tokens_out


@router.post("/chat/completions", response_model=None)
async def create_chat_completion(
    body: ChatCompletionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    engine: RoutingEngine = Depends(get_routing_engine),
) -> StreamingResponse | ChatCompletionResponse:
    all_candidates, api_keys = await _build_model_candidates(db, user, settings)
    candidates, profile, required_capability = _select_profile_and_candidates(body, all_candidates)

    if not candidates:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _NORMALIZED_UPSTREAM_ERROR)

    extra_kwargs = {
        k: v for k, v in (body.model_extra or {}).items() if k not in _GATEWAY_ONLY_EXTRA_FIELDS
    }
    make_invoke = _make_invoke_factory(body.messages, extra_kwargs, api_keys)

    try:
        outcome = await engine.route_by_model(
            candidates, make_invoke, profile=profile, required_capability=required_capability
        )
    except AllProvidersExhaustedError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, _NORMALIZED_UPSTREAM_ERROR
        ) from exc

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    if body.stream:
        return StreamingResponse(
            _stream_sse(
                outcome.result, completion_id, created, outcome.provider_name, outcome.model_id
            ),
            media_type="text/event-stream",
        )

    try:
        content, finish_reason, tokens_in, tokens_out = await _aggregate(outcome.result)
    except Exception as exc:  # noqa: BLE001 - normalized at the boundary
        logger.warning(
            "provider %s failed while aggregating response: %s", outcome.provider_name, exc
        )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _NORMALIZED_UPSTREAM_ERROR) from exc

    usage = None
    if tokens_in is not None or tokens_out is not None:
        total = (tokens_in or 0) + (tokens_out or 0)
        usage = ChatCompletionUsage(
            prompt_tokens=tokens_in, completion_tokens=tokens_out, total_tokens=total
        )

    return ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=outcome.model_id,
        provider_name=outcome.provider_name,
        model_id=outcome.model_id,
        choices=[
            ChatCompletionChoice(
                message=ChatCompletionMessageOut(content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )
