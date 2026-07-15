from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.security import (
    DecryptionError,
    InvalidTokenError,
    MissingMasterKeyError,
    create_access_token,
    decode_access_token,
    decrypt_key,
    encrypt_key,
    generate_master_key,
    hash_password,
    load_or_create_master_key,
    verify_password,
)


def make_settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


# --- Fernet encrypt/decrypt round-trip ----------------------------------------------


def test_encrypt_decrypt_round_trip() -> None:
    master_key = generate_master_key()
    plaintext = "sk-super-secret-provider-key"

    token = encrypt_key(plaintext, master_key)

    assert token != plaintext
    assert decrypt_key(token, master_key) == plaintext


def test_decrypt_with_wrong_master_key_raises() -> None:
    token = encrypt_key("sk-abc123", generate_master_key())

    with pytest.raises(DecryptionError):
        decrypt_key(token, generate_master_key())


def test_encrypt_with_missing_master_key_raises() -> None:
    with pytest.raises(MissingMasterKeyError):
        encrypt_key("sk-abc123", None)


def test_decrypt_with_missing_master_key_raises() -> None:
    with pytest.raises(MissingMasterKeyError):
        decrypt_key("whatever", None)


# --- Master key bootstrap ------------------------------------------------------------


def test_load_or_create_master_key_returns_existing_key_without_touching_disk(
    tmp_path: Path,
) -> None:
    existing_key = generate_master_key()
    settings = make_settings(master_encryption_key=existing_key)
    env_path = tmp_path / ".env"

    result = load_or_create_master_key(settings, env_path=env_path)

    assert result == existing_key
    assert not env_path.exists()


def test_load_or_create_master_key_generates_and_persists_when_absent(
    tmp_path: Path,
) -> None:
    settings = make_settings(master_encryption_key=None)
    env_path = tmp_path / ".env"

    result = load_or_create_master_key(settings, env_path=env_path)

    assert result  # a key was generated
    assert settings.master_encryption_key == result  # settings updated in place
    assert env_path.exists()
    assert f"MASTER_ENCRYPTION_KEY={result}" in env_path.read_text(encoding="utf-8")

    # the generated key actually works for encrypt/decrypt
    token = encrypt_key("sk-abc123", result)
    assert decrypt_key(token, result) == "sk-abc123"


def test_load_or_create_master_key_appends_to_existing_env_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("SOME_OTHER_VAR=hello\n", encoding="utf-8")
    settings = make_settings(master_encryption_key=None)

    result = load_or_create_master_key(settings, env_path=env_path)

    contents = env_path.read_text(encoding="utf-8")
    assert "SOME_OTHER_VAR=hello" in contents
    assert f"MASTER_ENCRYPTION_KEY={result}" in contents


# --- Password hashing -----------------------------------------------------------------


def test_password_hash_round_trip() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", password_hash) is True
    assert verify_password("wrong password", password_hash) is False


# --- JWT sessions ----------------------------------------------------------------------


def test_access_token_round_trip() -> None:
    settings = make_settings(jwt_secret="test-secret-that-is-long-enough-for-hs256")

    token = create_access_token(user_id=42, is_admin=True, settings=settings)
    payload = decode_access_token(token, settings)

    assert payload.user_id == 42
    assert payload.is_admin is True


def test_expired_access_token_raises() -> None:
    settings = make_settings(jwt_secret="test-secret-that-is-long-enough-for-hs256")

    token = create_access_token(user_id=1, is_admin=False, settings=settings, expires_minutes=-1)

    with pytest.raises(InvalidTokenError):
        decode_access_token(token, settings)


def test_access_token_with_wrong_secret_raises() -> None:
    settings = make_settings(jwt_secret="test-secret-that-is-long-enough-for-hs256")
    other_settings = make_settings(jwt_secret="different-secret-that-is-also-long-enough")

    token = create_access_token(user_id=1, is_admin=False, settings=settings)

    with pytest.raises(InvalidTokenError):
        decode_access_token(token, other_settings)


def test_garbage_token_raises() -> None:
    settings = make_settings(jwt_secret="test-secret-that-is-long-enough-for-hs256")

    with pytest.raises(InvalidTokenError):
        decode_access_token("not-a-real-token", settings)
