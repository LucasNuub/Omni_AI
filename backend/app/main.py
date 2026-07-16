"""FastAPI application entrypoint.

Wires up auth, admin (invites + provider enable/disable), liveness/status,
chat completions, provider key management + discovery, and the Model
Registry catalog. Images/compare land in a later phase.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import admin, auth, chat, health, models, providers
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import load_or_create_master_key
from app.db.bootstrap import ensure_admin_bootstrapped
from app.db.session import async_session_factory
from app.providers.registry import ensure_providers_seeded
from app.router.circuit_breaker import CircuitBreaker
from app.router.engine import RoutingEngine

settings = get_settings()
configure_logging()
load_or_create_master_key(settings)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.routing_engine = RoutingEngine(circuit_breaker=CircuitBreaker())
    async with async_session_factory() as session:
        await ensure_providers_seeded(session)
        await ensure_admin_bootstrapped(session, settings)
    yield


app = FastAPI(title="AI Gateway", version="0.1.0", lifespan=lifespan)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(chat.router)
app.include_router(providers.router)
app.include_router(models.router)
