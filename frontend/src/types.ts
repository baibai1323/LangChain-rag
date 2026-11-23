export interface User {
  id: string
  username: string
  role: 'user' | 'admin'
  status: string
  created_at: string
  last_login_at: string | null
  conversation_count?: number
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: User
}

export interface Kb {
  id: string
  name: string
  description: string
  embedding_model: string
  embedding_dim: number
  version: number
  created_at: string
  updated_at: string
  document_count: number
  chunk_count: number
}

export interface DocumentItem {
  id: string
  kb_id: string
  filename: string
  mime: string
  size: number
  status: 'pending' | 'processing' | 'ready' | 'failed'
  chunk_count: number
  token_count: number
  error: string | null
  file_hash: string
  created_at: string
  updated_at: string
}

export interface TaskItem {
  id: string
  doc_id: string
  stage: string
  progress: number
  status: 'running' | 'success' | 'failed'
  error: string | null
  started_at: string
  finished_at: string | null
}

export interface Citation {
  chunk_id: string
  doc_id: string
  doc_name: string
  page: number
  rank: number
  score: number
  quote: string
}

export interface ChatMessage {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  status: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  first_token_ms: number
  latency_ms: number
  from_cache: number
  created_at: string
  citations: Citation[]
}

export interface Conversation {
  id: string
  kb_id: string
  title: string
  is_pinned: number
  created_at: string
  updated_at: string
  message_count: number
}

export interface SearchHit {
  chunk_id: string
  doc_id: string
  doc_name: string
  page: number
  content: string
  score: number
  rerank_score: number | null
  source: string
}

export interface ChunkItem {
  id: string
  doc_id: string
  chunk_index: number
  content: string
  parent_content: string
  token_count: number
  char_count: number
}

export interface AdminStats {
  users: number
  conversations: number
  messages: number
  documents: number
  chunks: number
  knowledge_bases: number
  llm_calls_today: number
  tokens_today: number
  avg_latency_ms: number
  feedback_positive: number
  feedback_negative: number
}

export interface StreamHandlers {
  onStatus?: (data: { stage: string; message: string }) => void
  onRetrieval?: (data: { hits: Citation[]; rewritten?: string; cached?: boolean }) => void
  onDelta?: (text: string) => void
  onDone?: (data: Record<string, unknown>) => void
  onError?: (message: string) => void
}
