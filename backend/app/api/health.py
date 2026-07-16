"""Liveness + per-provider status — see SPEC.md sections 12 and 15.

``/status`` is what the frontend's traffic-light grid reads from: for each
currently-enabled provider, combine a live ``health_check()`` probe, the
circuit breaker's cooldown state, and today's ``QuotaUsage`` (shared-pool
row) into one ``{healthy, remaining_today, reset_at}`` entry.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.chat import get_routing_engine
from app.db.models import Provider, User
from app.db.models import QuotaUsage as QuotaUsageRow
from app.db.session import get_db
from app.providers.base import QuotaStatus
from app.providers.base import QuotaUsage as QuotaUsageSnapshot
from app.providers.registry import ADAPTERS
from app.router.engine import RoutingEngine

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str = "ok"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


class ProviderStatusEntry(BaseModel):
    healthy: bool
    remaining_today: int | None
    limit: int | None = None
    reset_at: datetime | None = None
    # Traffic-light bucket the frontend renders directly — computed here so
    # every consumer (Provider Status page, Admin toggle list) agrees on one
    # definition instead of each re-deriving thresholds from raw numbers.
    status: Literal["green", "yellow", "red"] = "green"
    cooling_down_until: datetime | None = None


_YELLOW_REMAINING_RATIO = 0.25


def _classify_status(
    healthy: bool, quota: QuotaStatus, cooling_down_until: datetime | None
) -> Literal["green", "yellow", "red"]:
    if not healthy or quota.exhausted or cooling_down_until is not None:
        return "red"
    if quota.limit and quota.remaining is not None:
        if (quota.remaining / quota.limit) <= _YELLOW_REMAINING_RATIO:
            return "yellow"
    return "green"


async def _quota_snapshot(db: AsyncSession, provider_name: str, today: date) -> QuotaUsageSnapshot:
    result = await db.execute(
        select(QuotaUsageRow).where(
            QuotaUsageRow.provider_name == provider_name,
            QuotaUsageRow.date == today,
            QuotaUsageRow.user_id.is_(None),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return QuotaUsageSnapshot(provider_name=provider_name, date=today, request_count=0)
    return QuotaUsageSnapshot(
        provider_name=row.provider_name,
        date=row.date,
        request_count=row.request_count,
        daily_limit=row.daily_limit,
    )


@router.get("/status", response_model=dict[str, ProviderStatusEntry])
async def get_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    engine: RoutingEngine = Depends(get_routing_engine),
) -> dict[str, ProviderStatusEntry]:
    result = await db.execute(
        select(Provider).where(Provider.enabled.is_(True)).order_by(Provider.priority)
    )
    providers = result.scalars().all()
    today = date.today()

    statuses: dict[str, ProviderStatusEntry] = {}
    for provider in providers:
        adapter = ADAPTERS.get(provider.name)
        if adapter is None:
            continue

        health_result = await adapter.health_check()
        usage = await _quota_snapshot(db, provider.name, today)
        quota = adapter.remaining_quota(usage)
        healthy = health_result.healthy and engine.circuit_breaker.is_available(provider.name)

        cooling_until = engine.circuit_breaker.cooling_down_until(provider.name)
        if cooling_until is not None and cooling_until <= datetime.now(UTC):
            cooling_until = None

        statuses[provider.name] = ProviderStatusEntry(
            healthy=healthy,
            remaining_today=quota.remaining,
            limit=quota.limit,
            reset_at=quota.reset_at,
            status=_classify_status(healthy, quota, cooling_until),
            cooling_down_until=cooling_until,
        )

    return statuses
