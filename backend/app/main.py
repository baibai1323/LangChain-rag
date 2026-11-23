from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from .api import admin, auth, chat, conversations, documents, kbs
from .config import settings
from .db import SessionLocal, close_db, init_db
from .llm import close_llm
from .models import User
from .security import hash_password

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = ROOT / "frontend" / "dist"


async def seed_admin() -> None:
    async with SessionLocal() as db:
        existing = (
            await db.execute(select(User).where(User.username == settings.admin_username))
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                User(
                    username=settings.admin_username,
                    password_hash=hash_password(settings.admin_password),
                    role="admin",
                )
            )
            await db.commit()
            logger.info("已创建内置管理员账号 %s", settings.admin_username)
        elif existing.role != "admin":
            existing.role = "admin"
            await db.commit()
            logger.info("已将 %s 提升为管理员", settings.admin_username)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201
    await init_db()
    await seed_admin()
    logger.info("服务启动完成：%s", settings.app_name)
    yield
    await close_llm()
    await close_db()


app = FastAPI(
    title=settings.app_name,
    description="基于 LangChain + 千问的电商知识库 RAG 问答系统",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(kbs.router)
app.include_router(documents.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(admin.router)


@app.get("/api/health", tags=["系统"], summary="健康检查")
async def health() -> dict:
    db_ok = True
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.app_name,
        "db": db_ok,
        "chat_model": settings.qwen_chat_model,
        "embedding_model": settings.qwen_embed_model,
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常 %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})


if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False, response_model=None)
async def spa(full_path: str) -> FileResponse | JSONResponse:
    if full_path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "接口不存在"})
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        status_code=200,
        content={
            "message": "后端已启动。前端尚未构建，请在 frontend 目录执行 npm install && npm run build，或使用 npm run dev 访问 5173 端口。",
            "docs": "/api/docs",
        },
    )
