from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_\u4e00-\u9fa5]+$")
    password: str = Field(min_length=6, max_length=64)


class LoginIn(BaseModel):
    username: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(ORMModel):
    id: str
    username: str
    role: str
    status: str
    created_at: datetime
    last_login_at: datetime | None = None


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=64)


class ProfileUpdateIn(BaseModel):
    nickname: str | None = Field(default=None, max_length=32)


# ---------- knowledge base ----------
class KbIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)


class KbOut(ORMModel):
    id: str
    name: str
    description: str
    embedding_model: str
    embedding_dim: int
    version: int
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    chunk_count: int = 0


class KbUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)


# ---------- documents / ingestion ----------
class DocumentOut(ORMModel):
    id: str
    kb_id: str
    filename: str
    mime: str
    size: int
    status: str
    chunk_count: int
    token_count: int
    error: str | None = None
    file_hash: str
    created_at: datetime
    updated_at: datetime


class TaskOut(ORMModel):
    id: str
    doc_id: str
    stage: str
    progress: int
    status: str
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class ChunkOut(ORMModel):
    id: str
    doc_id: str
    chunk_index: int
    content: str
    parent_content: str
    token_count: int
    char_count: int


# ---------- retrieval ----------
class SearchTestIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=6, ge=1, le=20)


class SearchHit(BaseModel):
    chunk_id: str
    doc_id: str
    doc_name: str
    page: int
    content: str
    score: float
    rerank_score: float | None = None
    source: str = "hybrid"


# ---------- conversations ----------
class MessageOut(ORMModel):
    id: str
    conversation_id: str
    role: str
    content: str
    status: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    first_token_ms: int
    latency_ms: int
    from_cache: int
    created_at: datetime
    citations: list["CitationOut"] = []


class CitationOut(ORMModel):
    chunk_id: str
    doc_id: str
    doc_name: str
    page: int
    rank: int
    score: float
    quote: str


class ConversationOut(ORMModel):
    id: str
    kb_id: str
    title: str
    is_pinned: int
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ConversationCreateIn(BaseModel):
    kb_id: str
    title: str | None = Field(default=None, max_length=100)


class ConversationUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    is_pinned: int | None = None


class ChatIn(BaseModel):
    conversation_id: str
    question: str = Field(min_length=1, max_length=2000)
    use_cache: bool = True


class FeedbackIn(BaseModel):
    rating: int = Field(ge=-1, le=1)
    comment: str = Field(default="", max_length=500)


# ---------- admin ----------
class AdminStats(BaseModel):
    users: int
    conversations: int
    messages: int
    documents: int
    chunks: int
    knowledge_bases: int
    llm_calls_today: int
    tokens_today: int
    avg_latency_ms: int
    feedback_positive: int
    feedback_negative: int


class UserAdminOut(UserOut):
    conversation_count: int = 0


class UserUpdateIn(BaseModel):
    role: str | None = Field(default=None, pattern="^(user|admin)$")
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


MessageOut.model_rebuild()
