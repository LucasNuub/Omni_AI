"""Key-at-rest encryption (Fernet) and auth primitives (JWT, password hashing).

See SPEC.md section 10 for the encryption design and section 13 for auth.

Honest scope: this stops provider keys from leaking via git history, casual
DB backups, or someone glancing at a DB dump. It does not protect against a
fully compromised host with access to both the DB and the running process's
memory/environment.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel

from app.core.config import Settings

logger = logging.getLogger(__name__)

_password_hasher = PasswordHasher()


class DecryptionError(RuntimeError):
    """Raised when a stored provider key cannot be decrypted."""


class MissingMasterKeyError(RuntimeError):
    """Raised when an operation needs a master key that was never configured."""


# --- Fernet key-at-rest encryption ------------------------------------------------


def generate_master_key() -> str:
    """Generate a new Fernet-compatible master key."""
    return Fernet.generate_key().decode("ascii")


def load_or_create_master_key(settings: Settings, env_path: Path = Path(".env")) -> str:
    """Return the configured master key, generating and persisting one if absent.

    Mirrors SPEC.md section 10: auto-generated on first run if absent, printed
    once with a warning to back it up. Losing it means every stored
    ``ProviderKey`` needs to be re-entered — there is no recovery path.
    """
    if settings.master_encryption_key:
        return settings.master_encryption_key

    key = generate_master_key()
    _persist_master_key(env_path, key)

    warning = (
        "No MASTER_ENCRYPTION_KEY was configured — generated a new one.\n"
        f"  MASTER_ENCRYPTION_KEY={key}\n"
        "BACK THIS UP. If it is lost, every stored provider key must be "
        "re-entered — there is no recovery path by design."
    )
    logger.warning(warning)
    print(warning)  # noqa: T201 - deliberate one-time operator-facing notice

    settings.master_encryption_key = key
    return key


def _persist_master_key(env_path: Path, key: str) -> None:
    line = f"MASTER_ENCRYPTION_KEY={key}\n"
    if env_path.exists():
        with env_path.open("a", encoding="utf-8") as f:
            f.write(line)
    else:
        env_path.write_text(line, encoding="utf-8")


def _fernet(master_key: str | None) -> Fernet:
    if not master_key:
        raise MissingMasterKeyError(
            "MASTER_ENCRYPTION_KEY is not set; call load_or_create_master_key() first."
        )
    return Fernet(master_key.encode("ascii"))


def encrypt_key(plaintext: str, master_key: str | None) -> str:
    """Encrypt a provider API key for storage in ``ProviderKey.encrypted_key``."""
    return _fernet(master_key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_key(token: str, master_key: str | None) -> str:
    """Decrypt a stored provider key. Only ever call this in-memory, right before use."""
    try:
        return _fernet(master_key).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError(
            "Stored key could not be decrypted with the current master key."
        ) from exc


# --- Password hashing --------------------------------------------------------------


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


# --- JWT sessions --------------------------------------------------------------------


class TokenPayload(BaseModel):
    user_id: int
    is_admin: bool
    exp: dt.datetime


class InvalidTokenError(RuntimeError):
    """Raised when a JWT session token is missing, malformed, or expired."""


def create_access_token(
    user_id: int,
    is_admin: bool,
    settings: Settings,
    expires_minutes: int | None = None,
) -> str:
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    expire = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=minutes)
    payload = {"user_id": user_id, "is_admin": is_admin, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> TokenPayload:
    try:
        raw = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Session token is invalid or expired.") from exc
    return TokenPayload.model_validate(raw)
