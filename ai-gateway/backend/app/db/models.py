"""SQLAlchemy 2 ORM models — see SPEC.md section 11."""

from __future__ import annotations

import enum
from datetime import date as date_
from datetime import datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class HealthStatus(enum.StrEnum):
    green = "green"
    yellow = "yellow"
    red = "red"


class ProviderKeyStatus(enum.StrEnum):
    pending = "pending"
    active = "active"
    invalid_key = "invalid_key"
    revoked = "revoked"


class AuthType(enum.StrEnum):
    api_key = "api_key"
    none = "none"
    local = "local"


class QualitySource(enum.StrEnum):
    benchmarked = "benchmarked"
    curated = "curated"
    unrated = "unrated"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    provider_keys: Mapped[list[ProviderKey]] = relationship(back_populates="user")
    quota_usages: Mapped[list[QuotaUsage]] = relationship(back_populates="user")
    request_logs: Mapped[list[RequestLog]] = relationship(back_populates="user")
    invites_created: Mapped[list[Invite]] = relationship(
        back_populates="created_by",
        foreign_keys="Invite.created_by_user_id",
    )


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    used_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[User] = relationship(
        back_populates="invites_created", foreign_keys=[created_by_user_id]
    )
    used_by: Mapped[User | None] = relationship(foreign_keys=[used_by_user_id])


class ProviderKey(Base):
    __tablename__ = "provider_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    provider_name: Mapped[str] = mapped_column(ForeignKey("providers.name"))
    nickname: Mapped[str | None] = mapped_column(String(100), default=None)
    encrypted_key: Mapped[str] = mapped_column(String)
    is_shared: Mapped[bool] = mapped_column(default=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    daily_usage_count: Mapped[int] = mapped_column(default=0)
    daily_usage_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    health_status: Mapped[HealthStatus] = mapped_column(
        Enum(HealthStatus, native_enum=False), default=HealthStatus.green
    )
    status: Mapped[ProviderKeyStatus] = mapped_column(
        Enum(ProviderKeyStatus, native_enum=False), default=ProviderKeyStatus.pending
    )

    user: Mapped[User | None] = relationship(back_populates="provider_keys")
    provider: Mapped[Provider] = relationship(back_populates="keys")


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    base_url: Mapped[str | None] = mapped_column(String(255), default=None)
    auth_type: Mapped[AuthType] = mapped_column(Enum(AuthType, native_enum=False))
    priority: Mapped[int] = mapped_column(default=0)
    enabled: Mapped[bool] = mapped_column(default=True)
    cooling_down_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    keys: Mapped[list[ProviderKey]] = relationship(back_populates="provider")
    models: Mapped[list[Model]] = relationship(back_populates="provider")


class Model(Base):
    __tablename__ = "models"
    __table_args__ = (
        UniqueConstraint("provider_name", "model_id", name="uq_model_provider_modelid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_name: Mapped[str] = mapped_column(ForeignKey("providers.name"))
    model_id: Mapped[str] = mapped_column(String(150))
    display_name: Mapped[str] = mapped_column(String(150))
    supports_vision: Mapped[bool] = mapped_column(default=False)
    supports_coding_hint: Mapped[int | None] = mapped_column(default=None)
    supports_reasoning_hint: Mapped[int | None] = mapped_column(default=None)
    context_length: Mapped[int | None] = mapped_column(default=None)
    speed_rating: Mapped[int | None] = mapped_column(default=None)
    free: Mapped[bool] = mapped_column(default=True)
    quality_source: Mapped[QualitySource] = mapped_column(
        Enum(QualitySource, native_enum=False), default=QualitySource.unrated
    )
    enabled: Mapped[bool] = mapped_column(default=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    provider: Mapped[Provider] = relationship(back_populates="models")


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    provider_name: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str] = mapped_column(String(150))
    endpoint: Mapped[str] = mapped_column(String(100))
    latency_ms: Mapped[float | None] = mapped_column(default=None)
    tokens_in: Mapped[int | None] = mapped_column(default=None)
    tokens_out: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(30))
    fallback_count: Mapped[int] = mapped_column(default=0)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="request_logs")


class QuotaUsage(Base):
    __tablename__ = "quota_usages"
    __table_args__ = (
        UniqueConstraint("user_id", "provider_name", "date", name="uq_quota_user_provider_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    provider_name: Mapped[str] = mapped_column(String(50))
    date: Mapped[date_] = mapped_column(Date)
    request_count: Mapped[int] = mapped_column(default=0)
    daily_limit: Mapped[int | None] = mapped_column(default=None)

    user: Mapped[User | None] = relationship(back_populates="quota_usages")
