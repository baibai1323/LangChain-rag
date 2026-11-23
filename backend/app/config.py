from __future__ import annotations

import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8-sig",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "电商知识库 RAG 问答系统"
    debug: bool = False

    # 千问 / DashScope
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_chat_model: str = "qwen-max"
    qwen_fast_model: str = "qwen-turbo"
    qwen_embed_model: str = "text-embedding-v3"
    qwen_embed_dim: int = 1024
    qwen_rerank_model: str = "gte-rerank-v2"
    qwen_rerank_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )
    llm_timeout: float = 120.0

    # 认证
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    admin_username: str = "admin"
    admin_password: str = "123456"
    # 只有明确部署在反向代理后面才信任 X-Forwarded-For，否则客户端可伪造 IP 绕过限流
    trust_proxy_headers: bool = False

    # 数据目录
    data_dir: Path = DATA_DIR

    # 检索参数
    chunk_size: int = 400
    chunk_overlap: int = 50
    parent_size: int = 1200
    vector_top_k: int = 20
    bm25_top_k: int = 20
    rerank_top_n: int = 6
    rrf_k: int = 60
    min_rerank_score: float = 0.05
    context_token_budget: int = 3500

    # 缓存
    cache_ttl_seconds: int = 3600
    semantic_cache_threshold: float = 0.95
    semantic_cache_max_entries: int = 300

    # 限流
    chat_rate_limit_per_minute: int = 30

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path.as_posix()}"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.uploads_dir, self.chroma_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)
        if not self.jwt_secret:
            secret_file = self.data_dir / "jwt_secret"
            if secret_file.exists():
                self.jwt_secret = secret_file.read_text(encoding="utf-8").strip()
            else:
                self.jwt_secret = secrets.token_hex(32)
                secret_file.write_text(self.jwt_secret, encoding="utf-8")


settings = Settings()
settings.ensure_dirs()
