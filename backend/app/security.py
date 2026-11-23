from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import settings
from .models import User

_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _encode(payload: dict[str, Any], expires: timedelta) -> str:
    data = dict(payload)
    data["exp"] = datetime.now(timezone.utc) + expires
    data["iat"] = datetime.now(timezone.utc)
    return jwt.encode(data, settings.jwt_secret, algorithm="HS256")


def create_access_token(user: User) -> str:
    return _encode(
        {"sub": user.id, "role": user.role, "tv": user.token_version, "typ": "access"},
        timedelta(minutes=settings.access_token_minutes),
    )


def create_refresh_token(user: User) -> str:
    return _encode(
        {"sub": user.id, "role": user.role, "tv": user.token_version, "typ": "refresh"},
        timedelta(days=settings.refresh_token_days),
    )


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError("token type mismatch")
    return payload
