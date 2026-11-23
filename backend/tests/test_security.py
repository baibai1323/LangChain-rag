from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings
from app.models import User
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def make_user(token_version: int = 1) -> User:
    return User(
        id="u" * 32,
        username="tester",
        password_hash="x",
        role="user",
        status="active",
        token_version=token_version,
    )


def test_password_hash_roundtrip() -> None:
    digest = hash_password("s3cret-pass")
    assert digest != "s3cret-pass"
    assert verify_password(digest, "s3cret-pass") is True


def test_verify_password_rejects_wrong_password_and_invalid_hash() -> None:
    digest = hash_password("s3cret-pass")
    assert verify_password(digest, "wrong") is False
    assert verify_password("not-an-argon2-hash", "s3cret-pass") is False


def test_access_token_contains_expected_claims() -> None:
    user = make_user(token_version=3)
    payload = decode_token(create_access_token(user), "access")
    assert payload["sub"] == user.id
    assert payload["role"] == "user"
    assert payload["tv"] == 3
    assert payload["typ"] == "access"


def test_decode_token_rejects_wrong_type() -> None:
    refresh = create_refresh_token(make_user())
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(refresh, "access")


def test_decode_token_rejects_expired_token() -> None:
    expired = jwt.encode(
        {
            "sub": "u" * 32,
            "typ": "access",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(expired, "access")


def test_decode_token_rejects_signature_from_other_secret() -> None:
    forged = jwt.encode({"sub": "u", "typ": "access"}, "another-secret", algorithm="HS256")
    with pytest.raises(jwt.InvalidSignatureError):
        decode_token(forged, "access")
