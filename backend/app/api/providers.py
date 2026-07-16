"""Provider key management — see SPEC.md sections 9, 10, and 12.

``POST /providers/keys`` kicks off the discovery pipeline
(``discovery/scanner.py``) as a FastAPI background task and returns
immediately with ``status: pending``; the frontend polls
``GET /providers/keys/{id}/status`` for the live checklist. The background
task opens its own DB session (``async_session_factory``) rather than
reusing the request-scoped one, which FastAPI closes once the response is
sent — before the background task actually runs.

Keys are never returned in full past initial entry — list/status responses
only ever carry a masked tail, decrypted in-memory just long enough to mask
it (SPEC.md section 10).
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.config import Settings, get_settings
from app.core.security import DecryptionError, decrypt_key, encrypt_key
from app.db.models import ProviderKey as ProviderKeyRow
from app.db.models import ProviderKeyStatus, User
from app.db.models import QuotaUsage as QuotaUsageRow
from app.db.session import async_session_factory, get_db
from app.discovery.scanner import get_progress, run_discovery_pipeline
from app.providers.registry import ADAPTERS

router = APIRouter(prefix="/providers", tags=["providers"])


def mask_key(plaintext: str) -> str:
    """``sk-actualsecretvalue`` -> ``sk-...alue`` (SPEC.md section 10's example shape)."""
    if len(plaintext) <= 7:
        return "***"
    return f"{plaintext[:3]}...{plaintext[-4:]}"


class AddProviderKeyRequest(BaseModel):
    provider_name: str
    api_key: str | None = None
    nickname: str | None = None
    is_shared: bool = False


class ProviderKeyResponse(BaseModel):
    id: int
    provider_name: str
    nickname: str | None
    masked_key: str
    is_shared: bool
    health_status: str
    status: str
    added_at: datetime
    last_used_at: datetime | None
    daily_usage_count: int
    daily_limit: int | None


class DiscoveryStatusResponse(BaseModel):
    provider_key_id: int
    outcome: str
    steps: dict[str, str] = {}
    models_added: int = 0
    error: str | None = None


def _mask_stored_key(key: ProviderKeyRow, settings: Settings) -> str:
    if not key.encrypted_key:
        return "(none)"
    try:
        plaintext = decrypt_key(key.encrypted_key, settings.master_encryption_key)
    except DecryptionError:
        return "(undecryptable)"
    return mask_key(plaintext) if plaintext else "(none)"


async def _to_response(
    db: AsyncSession, key: ProviderKeyRow, settings: Settings
) -> ProviderKeyResponse:
    # daily_limit isn't tracked on ProviderKey itself — it lives on today's
    # QuotaUsage row for this key's (provider_name, user_id), same lookup
    # chat.py's _quota_snapshot does for routing decisions.
    quota_user_id = None if key.is_shared else key.user_id
    result = await db.execute(
        select(QuotaUsageRow).where(
            QuotaUsageRow.provider_name == key.provider_name,
            QuotaUsageRow.date == date.today(),
            QuotaUsageRow.user_id.is_(None)
            if quota_user_id is None
            else QuotaUsageRow.user_id == quota_user_id,
        )
    )
    quota_row = result.scalar_one_or_none()

    return ProviderKeyResponse(
        id=key.id,
        provider_name=key.provider_name,
        nickname=key.nickname,
        masked_key=_mask_stored_key(key, settings),
        is_shared=key.is_shared,
        health_status=key.health_status.value,
        status=key.status.value,
        added_at=key.added_at,
        last_used_at=key.last_used_at,
        daily_usage_count=key.daily_usage_count,
        daily_limit=quota_row.daily_limit if quota_row else None,
    )


async def _get_key_or_404(db: AsyncSession, key_id: int) -> ProviderKeyRow:
    key = await db.get(ProviderKeyRow, key_id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider key not found.")
    return key


def _authorize_view(key: ProviderKeyRow, user: User) -> None:
    if key.is_shared or key.user_id == user.id or user.is_admin:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view this key.")


def _authorize_manage(key: ProviderKeyRow, user: User) -> None:
    if key.is_shared:
        if not user.is_admin:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Only admins can manage a shared-pool key."
            )
        return
    if key.user_id != user.id and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to manage this key.")


async def _run_discovery_background(
    provider_key_id: int, provider_name: str, plaintext_api_key: str | None
) -> None:
    adapter = ADAPTERS.get(provider_name)
    if adapter is None:
        return

    settings = get_settings()
    async with async_session_factory() as session:
        key_row = await session.get(ProviderKeyRow, provider_key_id)
        if key_row is None:
            return
        await run_discovery_pipeline(
            session,
            key_row,
            adapter,
            plaintext_api_key,
            benchmark_sample_size=settings.discovery_benchmark_sample_size,
        )


@router.post("/keys", response_model=ProviderKeyResponse, status_code=status.HTTP_201_CREATED)
async def add_provider_key(
    body: AddProviderKeyRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> ProviderKeyResponse:
    if body.provider_name not in ADAPTERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown provider: {body.provider_name}")
    if body.is_shared and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can add a shared-pool key.")

    key_row = ProviderKeyRow(
        user_id=None if body.is_shared else user.id,
        provider_name=body.provider_name,
        nickname=body.nickname,
        encrypted_key=encrypt_key(body.api_key or "", settings.master_encryption_key),
        is_shared=body.is_shared,
        status=ProviderKeyStatus.pending,
    )
    db.add(key_row)
    await db.commit()
    await db.refresh(key_row)

    background_tasks.add_task(
        _run_discovery_background, key_row.id, body.provider_name, body.api_key
    )

    return await _to_response(db, key_row, settings)


@router.get("/keys", response_model=list[ProviderKeyResponse])
async def list_provider_keys(
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> list[ProviderKeyResponse]:
    result = await db.execute(
        select(ProviderKeyRow)
        .where(or_(ProviderKeyRow.user_id == user.id, ProviderKeyRow.is_shared.is_(True)))
        .order_by(ProviderKeyRow.added_at.desc())
    )
    return [await _to_response(db, key, settings) for key in result.scalars().all()]


_FALLBACK_OUTCOME = {
    ProviderKeyStatus.pending: "running",
    ProviderKeyStatus.active: "success",
    ProviderKeyStatus.invalid_key: "invalid_key",
    ProviderKeyStatus.revoked: "error",
}


@router.get("/keys/{key_id}/status", response_model=DiscoveryStatusResponse)
async def get_provider_key_status(
    key_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiscoveryStatusResponse:
    key = await _get_key_or_404(db, key_id)
    _authorize_view(key, user)

    progress = get_progress(key_id)
    if progress is not None:
        return DiscoveryStatusResponse(
            provider_key_id=key_id,
            outcome=progress.outcome.value,
            steps={step.value: step_status.value for step, step_status in progress.steps.items()},
            models_added=progress.models_added,
            error=progress.error,
        )

    # No in-memory progress for this process lifetime (never scanned, or the
    # server restarted since) — fall back to the persisted status, with no
    # per-step detail available.
    error = "This key has been revoked." if key.status == ProviderKeyStatus.revoked else None
    return DiscoveryStatusResponse(
        provider_key_id=key_id, outcome=_FALLBACK_OUTCOME[key.status], error=error
    )


@router.post("/keys/{key_id}/rescan", response_model=ProviderKeyResponse)
async def rescan_provider_key(
    key_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> ProviderKeyResponse:
    key = await _get_key_or_404(db, key_id)
    _authorize_manage(key, user)

    try:
        plaintext = (
            decrypt_key(key.encrypted_key, settings.master_encryption_key)
            if key.encrypted_key
            else None
        )
    except DecryptionError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Stored key could not be decrypted."
        ) from exc

    key.status = ProviderKeyStatus.pending
    await db.commit()
    await db.refresh(key)

    background_tasks.add_task(
        _run_discovery_background, key.id, key.provider_name, plaintext or None
    )
    return await _to_response(db, key, settings)


@router.delete("/keys/{key_id}", response_model=ProviderKeyResponse)
async def delete_provider_key(
    key_id: int,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> ProviderKeyResponse:
    key = await _get_key_or_404(db, key_id)
    _authorize_manage(key, user)

    key.status = ProviderKeyStatus.revoked
    await db.commit()
    await db.refresh(key)
    return await _to_response(db, key, settings)
