"""Invite-link + JWT auth — see SPEC.md sections 12 and 13.

No public signup: an admin generates an invite (``/admin/invite``), the
recipient redeems it with a chosen password (``/auth/invite/redeem``) and
gets a JWT session back, same as ``/auth/login`` thereafter.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.models import Invite, User
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer_scheme = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class InviteRedeemRequest(BaseModel):
    code: str
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials, settings)
    except InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session") from exc

    user = await db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin privileges required")
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    token = create_access_token(user.id, user.is_admin, settings)
    return TokenResponse(access_token=token)


@router.post("/invite/redeem", response_model=TokenResponse)
async def redeem_invite(
    body: InviteRedeemRequest,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    result = await db.execute(select(Invite).where(Invite.code == body.code))
    invite = result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
    if invite.used_by_user_id is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invite already used")
    if invite.expires_at < datetime.utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invite has expired")

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already registered")

    user = User(email=body.email, password_hash=hash_password(body.password), is_admin=False)
    db.add(user)
    await db.flush()

    invite.used_by_user_id = user.id
    await db.commit()

    token = create_access_token(user.id, user.is_admin, settings)
    return TokenResponse(access_token=token)
