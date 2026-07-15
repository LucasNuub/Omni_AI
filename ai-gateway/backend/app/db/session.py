"""Async SQLAlchemy engine/session setup."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()
settings.db_path.parent.mkdir(parents=True, exist_ok=True)

# aiosqlite connections are bound to the event loop that created them.
# NullPool opens a fresh connection per checkout instead of pooling one
# across loops — the standard, recommended setup for async SQLite, and it
# also means tests can freely mix a throwaway asyncio.run() loop (fixture
# setup) with the TestClient's own loop without "different loop" errors.
engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
