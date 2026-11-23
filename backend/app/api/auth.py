from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import AuditLog, User, utcnow
from ..schemas import (
    LoginIn,
    PasswordChangeIn,
    RefreshIn,
    RegisterIn,
    TokenOut,
    UserOut,
)
from ..security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password_async,
    verify_password_async,
)
from ..services.ratelimit import auth_limiter

router = APIRouter(prefix="/api/auth", tags=["认证"])


def _client_ip(request: Request) -> str:
    """取客户端 IP：默认不信任 X-Forwarded-For，避免客户端伪造 IP 绕过限流。"""
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _find_user(db: AsyncSession, username: str) -> User | None:
    return (
        await db.execute(select(User).where(func.lower(User.username) == username.strip().lower()))
    ).scalar_one_or_none()


def _tokens(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user),
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=TokenOut, summary="注册")
async def register(data: RegisterIn, request: Request, db: AsyncSession = Depends(get_db)) -> TokenOut:
    auth_limiter.check(_client_ip(request))
    if await _find_user(db, data.username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已被注册")
    user = User(
        username=data.username.strip(),
        password_hash=await hash_password_async(data.password),
        role="user",
    )
    db.add(user)
    db.add(
        AuditLog(
            user_id=user.id,
            username=user.username,
            action="register",
            target=user.username,
            ip=_client_ip(request),
        )
    )
    await db.commit()
    await db.refresh(user)
    return _tokens(user)


@router.post("/login", response_model=TokenOut, summary="登录")
async def login(data: LoginIn, request: Request, db: AsyncSession = Depends(get_db)) -> TokenOut:
    auth_limiter.check(_client_ip(request))
    user = await _find_user(db, data.username)
    if user is None or not await verify_password_async(user.password_hash, data.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用，请联系管理员")
    user.last_login_at = utcnow()
    db.add(
        AuditLog(
            user_id=user.id,
            username=user.username,
            action="login",
            target=user.username,
            ip=_client_ip(request),
        )
    )
    await db.commit()
    await db.refresh(user)
    return _tokens(user)


@router.post("/refresh", response_model=TokenOut, summary="刷新令牌")
async def refresh(data: RefreshIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    try:
        payload = decode_token(data.refresh_token, "refresh")
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新令牌无效或已过期"
        ) from exc
    user = await db.get(User, payload.get("sub", ""))
    if user is None or user.status != "active" or user.token_version != payload.get("tv"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请重新登录")
    return _tokens(user)


@router.post("/logout", summary="退出登录")
async def logout(user: User = Depends(get_current_user)) -> dict[str, str]:
    # JWT 无状态，客户端清除令牌即可；如需强制下线可提升 token_version
    return {"message": "已退出登录"}


@router.get("/me", response_model=UserOut, summary="当前用户")
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/password", response_model=TokenOut, summary="修改密码")
async def change_password(
    data: PasswordChangeIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TokenOut:
    if not await verify_password_async(user.password_hash, data.old_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码不正确")
    if data.old_password == data.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能与原密码相同")
    user.password_hash = await hash_password_async(data.new_password)
    user.token_version += 1
    db.add(
        AuditLog(
            user_id=user.id,
            username=user.username,
            action="change_password",
            target=user.username,
            ip=_client_ip(request),
        )
    )
    await db.commit()
    await db.refresh(user)
    return _tokens(user)
