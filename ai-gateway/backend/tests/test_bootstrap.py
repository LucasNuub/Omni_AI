from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.bootstrap import ensure_admin_bootstrapped
from app.db.models import User


async def test_admin_bootstrap_when_empty(db_session: AsyncSession) -> None:
    # Clear any users created by other tests to ensure a clean slate
    await db_session.execute(delete(User))
    await db_session.commit()

    settings = Settings(
        admin_email="testadmin@example.com",
        admin_bootstrap_password="testpassword123",
    )

    await ensure_admin_bootstrapped(db_session, settings)

    # Verify that the admin user was created correctly
    result = await db_session.execute(select(User).where(User.email == "testadmin@example.com"))
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.is_admin is True

    # Verify that running it again does not create duplicate users
    await ensure_admin_bootstrapped(db_session, settings)
    result = await db_session.execute(select(User))
    users = result.scalars().all()
    assert len(users) == 1


async def test_admin_bootstrap_skipped_when_not_empty(db_session: AsyncSession) -> None:
    # Set up an existing user
    await db_session.execute(delete(User))
    existing = User(email="existing@example.com", password_hash="hash", is_admin=False)
    db_session.add(existing)
    await db_session.commit()

    settings = Settings(
        admin_email="testadmin@example.com",
        admin_bootstrap_password="testpassword123",
    )

    await ensure_admin_bootstrapped(db_session, settings)

    # Verify that no bootstrap user was added
    result = await db_session.execute(select(User))
    users = result.scalars().all()
    assert len(users) == 1
    assert users[0].email == "existing@example.com"
