"""Admin endpoints — invites plus provider enable/disable.

The usage dashboard (also under ``/admin`` per SPEC.md section 12) lands in
a later phase alongside the request logging it depends on.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_admin
from app.core.config import Settings, get_settings
from app.db.models import Invite, Provider, User
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


class InviteResponse(BaseModel):
    code: str
    expires_at: datetime


@router.post("/invite", response_model=InviteResponse)
async def create_invite(
    admin: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> InviteResponse:
    code = secrets.token_urlsafe(24)
    expires_at = datetime.utcnow() + timedelta(hours=settings.invite_expire_hours)

    invite = Invite(code=code, created_by_user_id=admin.id, expires_at=expires_at)
    db.add(invite)
    await db.commit()

    return InviteResponse(code=code, expires_at=expires_at)


class ProviderToggleRequest(BaseModel):
    provider_name: str


class ProviderToggleResponse(BaseModel):
    provider_name: str
    enabled: bool


async def _get_provider_or_404(db: AsyncSession, provider_name: str) -> Provider:
    result = await db.execute(select(Provider).where(Provider.name == provider_name))
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown provider: {provider_name}")
    return provider


@router.post("/provider/enable", response_model=ProviderToggleResponse)
async def enable_provider(
    body: ProviderToggleRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ProviderToggleResponse:
    provider = await _get_provider_or_404(db, body.provider_name)
    provider.enabled = True
    await db.commit()
    return ProviderToggleResponse(provider_name=provider.name, enabled=True)


@router.post("/provider/disable", response_model=ProviderToggleResponse)
async def disable_provider(
    body: ProviderToggleRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ProviderToggleResponse:
    provider = await _get_provider_or_404(db, body.provider_name)
    provider.enabled = False
    await db.commit()
    return ProviderToggleResponse(provider_name=provider.name, enabled=False)
