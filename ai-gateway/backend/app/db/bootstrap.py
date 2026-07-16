import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import hash_password
from app.db.models import User

logger = logging.getLogger(__name__)


async def ensure_admin_bootstrapped(session: AsyncSession, settings: Settings) -> None:
    """Create a single admin account on startup if the users table is empty.

    Log a warning instructing the administrator to change the password immediately.
    """
    if not settings.admin_email or not settings.admin_bootstrap_password:
        return

    # Check if any user already exists
    result = await session.execute(select(User))
    first_user = result.scalars().first()
    if first_user is not None:
        return

    # Create the admin user
    admin_user = User(
        email=settings.admin_email,
        password_hash=hash_password(settings.admin_bootstrap_password),
        is_admin=True,
    )
    session.add(admin_user)
    await session.commit()

    warning_msg = (
        "\n============================================================\n"
        f"ADMIN USER BOOTSTRAPPED: {settings.admin_email}\n"
        "PLEASE CHANGE THIS PASSWORD IMMEDIATELY AFTER FIRST LOGIN.\n"
        "============================================================"
    )
    logger.warning(warning_msg)
    print(warning_msg)  # noqa: T201 - deliberate operator warning notice
