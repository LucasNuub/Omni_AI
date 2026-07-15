"""Shared fixtures for API contract tests.

Env vars (DB path, master key, JWT secret) must be set *before* anything
imports ``app.main`` — its module-level setup reads them once via the
cached ``get_settings()``. The schema is created through a throwaway
engine so the app's own engine (``app.db.session.engine``) never touches a
connection before the ``TestClient``'s event loop exists; aiosqlite
connections are loop-bound, so reusing one across loops breaks.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

_tmp_dir = Path(tempfile.mkdtemp(prefix="ai-gateway-test-"))
os.environ.setdefault("DB_PATH", str(_tmp_dir / "test.db"))
os.environ.setdefault("MASTER_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-that-is-long-enough-for-hs256")

from app.core.config import get_settings  # noqa: E402
from app.core.security import create_access_token, encrypt_key, hash_password  # noqa: E402
from app.db.models import (  # noqa: E402
    Base,
    Model,
    Provider,
    ProviderKeyStatus,
    QualitySource,
    User,
)
from app.db.models import ProviderKey as ProviderKeyRow  # noqa: E402
from app.db.session import async_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.providers.registry import ensure_providers_seeded  # noqa: E402


async def _create_schema() -> None:
    settings = get_settings()
    schema_engine = create_async_engine(settings.database_url)
    async with schema_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await schema_engine.dispose()


asyncio.run(_create_schema())


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A raw DB session for tests that call discovery/scanner.py directly.

    NullPool (app/db/session.py) means this is safe to use even in tests
    that don't also touch the ``client`` fixture's TestClient loop.
    """
    async with async_session_factory() as session:
        yield session


MakeUser = Callable[..., tuple[int, str]]
AddProviderKey = Callable[..., None]


@pytest.fixture
def make_user() -> MakeUser:
    """Create a user (optionally admin) directly in the DB and mint a bearer token."""

    async def _make(email: str, *, is_admin: bool = False) -> tuple[int, str]:
        settings = get_settings()
        async with async_session_factory() as session:
            user = User(email=email, password_hash=hash_password("irrelevant"), is_admin=is_admin)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            token = create_access_token(user.id, user.is_admin, settings)
            return user.id, token

    def _make_sync(email: str, *, is_admin: bool = False) -> tuple[int, str]:
        return asyncio.run(_make(email, is_admin=is_admin))

    return _make_sync


@pytest.fixture
def add_provider_key() -> AddProviderKey:
    """Insert an active ProviderKey row (shared pool by default)."""

    async def _add(
        provider_name: str,
        plaintext_key: str,
        *,
        user_id: int | None = None,
        is_shared: bool = True,
    ) -> None:
        settings = get_settings()
        async with async_session_factory() as session:
            session.add(
                ProviderKeyRow(
                    user_id=user_id,
                    provider_name=provider_name,
                    encrypted_key=encrypt_key(plaintext_key, settings.master_encryption_key),
                    is_shared=is_shared,
                    status=ProviderKeyStatus.active,
                )
            )
            await session.commit()

    def _add_sync(
        provider_name: str,
        plaintext_key: str,
        *,
        user_id: int | None = None,
        is_shared: bool = True,
    ) -> None:
        asyncio.run(_add(provider_name, plaintext_key, user_id=user_id, is_shared=is_shared))

    return _add_sync


SeedModel = Callable[..., None]


@pytest.fixture
def seed_model() -> SeedModel:
    """Insert a ``Model`` row directly, for tests of GET /models.

    Sync-wrapped like the other DB-writing fixtures here: mixing this with
    an ``async def`` test (needed for the async ``db_session`` fixture)
    alongside sync fixtures like ``client``/``make_user`` breaks, since
    those call ``asyncio.run()`` internally and that can't nest inside a
    pytest-asyncio test's already-running loop.
    """

    async def _seed(provider_name: str, model_id: str, **overrides: object) -> None:
        defaults: dict[str, object] = {
            "display_name": model_id,
            "supports_vision": False,
            "supports_coding_hint": None,
            "supports_reasoning_hint": None,
            "context_length": None,
            "speed_rating": None,
            "free": True,
            "quality_source": QualitySource.unrated,
            "enabled": True,
        }
        defaults.update(overrides)
        async with async_session_factory() as session:
            result = await session.execute(
                select(Model).where(
                    Model.provider_name == provider_name, Model.model_id == model_id
                )
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                session.add(Model(provider_name=provider_name, model_id=model_id, **defaults))
            else:
                # Upsert: two tests seeding the same (provider, model_id) is
                # common (e.g. re-seeding "llama-3.3-70b-versatile" on groq),
                # and this shared, persistent test DB has no per-test reset.
                for key, value in defaults.items():
                    setattr(existing, key, value)
            await session.commit()

    def _seed_sync(provider_name: str, model_id: str, **overrides: object) -> None:
        asyncio.run(_seed(provider_name, model_id, **overrides))

    return _seed_sync


SetProviderEnabled = Callable[[str, bool], None]


@pytest.fixture
def set_provider_enabled() -> SetProviderEnabled:
    """Force a provider's ``enabled`` flag, seeding it first if needed.

    Tests share one persistent DB across the whole session, so a test that
    cares about a provider's enabled state should set it explicitly rather
    than assume whatever an earlier test left behind.
    """

    async def _set(provider_name: str, enabled: bool) -> None:
        async with async_session_factory() as session:
            await ensure_providers_seeded(session)
            result = await session.execute(select(Provider).where(Provider.name == provider_name))
            provider = result.scalar_one()
            provider.enabled = enabled
            await session.commit()

    def _set_sync(provider_name: str, enabled: bool) -> None:
        asyncio.run(_set(provider_name, enabled))

    return _set_sync


ALL_PROVIDER_NAMES = (
    "groq",
    "gemini",
    "openrouter",
    "pollinations",
    "huggingface",
    "deepseek",
    "ollama",
)

ResetProviderModels = Callable[[str], None]


@pytest.fixture
def reset_provider_models() -> ResetProviderModels:
    """Disable every existing ``Model`` row for a provider.

    Tests share one persistent DB across the whole session, so a test that
    calls ``seed_model`` for a provider would otherwise see stray rows an
    earlier test left enabled on that same provider too.
    """

    async def _reset(provider_name: str) -> None:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Model).where(Model.provider_name == provider_name)
            )
            for row in result.scalars().all():
                row.enabled = False
            await session.commit()

    def _reset_sync(provider_name: str) -> None:
        asyncio.run(_reset(provider_name))

    return _reset_sync


OnlyProvidersEnabled = Callable[[set[str]], None]


@pytest.fixture
def only_providers_enabled(
    set_provider_enabled: SetProviderEnabled, reset_provider_models: ResetProviderModels
) -> OnlyProvidersEnabled:
    """Enable exactly ``names`` and disable every other known provider.

    Tests that exercise routing/status against fake adapters must not leave
    any *real* adapter enabled, or the endpoint under test will make a real
    network call to whichever provider wasn't accounted for. Also resets any
    ``Model`` rows on the newly-enabled providers, so a test using
    ``seed_model`` starts from a clean slate rather than also routing to
    whatever an earlier test left enabled on the same provider.
    """

    def _only(names: set[str]) -> None:
        for name in ALL_PROVIDER_NAMES:
            set_provider_enabled(name, name in names)
        for name in names:
            reset_provider_models(name)

    return _only
