from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import settings
from .models import User

_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)

# 单次哈希占 64MiB，必须限制并发，否则 100 个登录同时进来会瞬间吃掉 6GB 内存。
# 用 threading 信号量而不是 asyncio.Semaphore：它与事件循环解绑，测试里多个 loop 也安全。
# 8 并发 × 64MiB ≈ 512MiB 峰值，在 100 并发登录下仍留足余量。
_HASH_CONCURRENCY = 8
_hash_gate = threading.BoundedSemaphore(_HASH_CONCURRENCY)


def hash_password(password: str) -> str:
    with _hash_gate:
        return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        with _hash_gate:
            return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


async def hash_password_async(password: str) -> str:
    """在线程池里做哈希，避免阻塞事件循环；并发度由信号量限制。"""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password_hash: str, password: str) -> bool:
    """在线程池里校验哈希，避免登录风暴把事件循环卡死。"""
    return await asyncio.to_thread(verify_password, password_hash, password)


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
