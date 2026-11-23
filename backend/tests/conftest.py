"""pytest 公共 fixture：独立临时 SQLite、依赖覆盖、预置账号。

原则（见 .dsh/skills/unit-test-rag/SKILL.md）：
- 不连真实 data/app.db，不连网络，不启动 lifespan（避免 init_db 写真实库）。
- 每个测试一份临时库，互不污染。
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import KnowledgeBase, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.ratelimit import auth_limiter, chat_limiter  # noqa: E402

ADMIN_PASSWORD = "admin123456"
USER_PASSWORD = "user123456"


@pytest.fixture(autouse=True)
def reset_rate_limiters() -> Iterator[None]:
    """登录/注册限流是进程级状态，测试间必须清空，否则第 11 次注册就 429。"""
    auth_limiter._hits.clear()
    chat_limiter._hits.clear()
    yield
    auth_limiter._hits.clear()
    chat_limiter._hits.clear()


@pytest.fixture()
def tmp_path() -> Iterator[Path]:
    """替代 pytest 内置 tmp_path。

    本机沙箱创建的 `%TEMP%\\pytest-of-*` 目录 ACL 异常，pytest 收尾扫描时会
    WinError 5 崩溃；这里改用项目内自建目录，测试后清理。
    """
    import shutil
    import uuid

    workdir = BACKEND / ".pytest-work" / uuid.uuid4().hex
    workdir.mkdir(parents=True)
    try:
        yield workdir
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """同步建表到临时文件，再交给异步引擎使用，避免跨事件循环复用连接。"""
    path = tmp_path / "test.db"
    sync_engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(sync_engine)
    admin = User(
        username="admin",
        password_hash=hash_password(ADMIN_PASSWORD),
        role="admin",
    )
    user = User(
        username="alice",
        password_hash=hash_password(USER_PASSWORD),
        role="user",
    )
    kb = KnowledgeBase(id="kbtest1", name="测试知识库", description="")
    with Session(sync_engine) as session:
        session.add_all([admin, user, kb])
        session.commit()
    sync_engine.dispose()
    return path


@pytest.fixture()
def client(db_path: Path) -> Iterator[TestClient]:
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool
    )
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    # 不用 with TestClient(...)：避免触发 lifespan 的 init_db / seed_admin 写真实库
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()
        asyncio.run(async_engine.dispose())


def login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {login(client, username, password)}"}


@pytest.fixture()
def admin_headers(client: TestClient) -> dict[str, str]:
    return auth_headers(client, "admin", ADMIN_PASSWORD)


@pytest.fixture()
def user_headers(client: TestClient) -> dict[str, str]:
    return auth_headers(client, "alice", USER_PASSWORD)
