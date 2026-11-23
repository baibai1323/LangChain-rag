import { api } from './client'
import type {
  AdminStats,
  ChatMessage,
  ChunkItem,
  Conversation,
  DocumentItem,
  Kb,
  SearchHit,
  TaskItem,
  TokenResponse,
  User
} from '@/types'

export { streamChat, ApiError } from './client'
export type { StreamHandlers } from '@/types'

export interface KbStats {
  kb_id: string
  documents: number
  ready_documents: number
  chunks: number
  tokens: number
}

export interface SeriesPoint {
  date: string
  messages: number
}

export interface AuditLogItem {
  id: string
  username: string
  action: string
  target: string
  detail: string
  ip: string
  created_at: string
}

export interface LlmCallItem {
  id: string
  purpose: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
  status: string
  created_at: string
}

export const authApi = {
  login: (username: string, password: string) =>
    api.post<TokenResponse>('/api/auth/login', { username, password }),
  register: (username: string, password: string) =>
    api.post<TokenResponse>('/api/auth/register', { username, password }),
  me: () => api.get<User>('/api/auth/me'),
  logout: () => api.post<{ message: string }>('/api/auth/logout'),
  changePassword: (old_password: string, new_password: string) =>
    api.post<TokenResponse>('/api/auth/password', { old_password, new_password })
}

export const kbApi = {
  list: () => api.get<Kb[]>('/api/kbs'),
  get: (id: string) => api.get<Kb>(`/api/kbs/${id}`),
  create: (name: string, description = '') => api.post<Kb>('/api/kbs', { name, description }),
  update: (id: string, payload: { name?: string; description?: string }) =>
    api.patch<Kb>(`/api/kbs/${id}`, payload),
  remove: (id: string) => api.delete<{ message: string }>(`/api/kbs/${id}`),
  stats: (id: string) => api.get<KbStats>(`/api/kbs/${id}/stats`),
  searchTest: (id: string, query: string, top_k = 6) =>
    api.post<SearchHit[]>(`/api/kbs/${id}/search-test`, { query, top_k })
}

export const docApi = {
  list: (kbId: string) => api.get<DocumentItem[]>(`/api/kbs/${kbId}/documents`),
  get: (id: string) => api.get<DocumentItem>(`/api/documents/${id}`),
  upload: (kbId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.upload<{ document: DocumentItem; task_id: string }>(`/api/kbs/${kbId}/documents`, form)
  },
  chunks: (docId: string, offset = 0, limit = 50) =>
    api.get<{ total: number; items: ChunkItem[] }>(
      `/api/documents/${docId}/chunks?offset=${offset}&limit=${limit}`
    ),
  reindex: (docId: string) => api.post<{ task_id: string; message: string }>(`/api/documents/${docId}/reindex`),
  remove: (docId: string) => api.delete<{ message: string }>(`/api/documents/${docId}`)
}

export const taskApi = {
  get: (id: string) => api.get<TaskItem>(`/api/tasks/${id}`),
  listByKb: (kbId: string) => api.get<TaskItem[]>(`/api/kbs/${kbId}/tasks`)
}

export const convApi = {
  list: (kbId?: string) =>
    api.get<Conversation[]>(`/api/conversations${kbId ? `?kb_id=${encodeURIComponent(kbId)}` : ''}`),
  create: (kbId: string, title?: string) =>
    api.post<Conversation>('/api/conversations', { kb_id: kbId, title }),
  get: (id: string) => api.get<Conversation>(`/api/conversations/${id}`),
  update: (id: string, payload: { title?: string; is_pinned?: number }) =>
    api.patch<Conversation>(`/api/conversations/${id}`, payload),
  remove: (id: string) => api.delete<{ message: string }>(`/api/conversations/${id}`),
  messages: (id: string, limit = 100) =>
    api.get<ChatMessage[]>(`/api/conversations/${id}/messages?limit=${limit}`),
  feedback: (messageId: string, rating: number, comment = '') =>
    api.post<{ message: string }>(`/api/messages/${messageId}/feedback`, { rating, comment })
}

export const adminApi = {
  stats: () => api.get<AdminStats>('/api/admin/stats'),
  series: () => api.get<SeriesPoint[]>('/api/admin/series'),
  users: () => api.get<User[]>('/api/admin/users'),
  updateUser: (id: string, payload: { role?: string; status?: string }) =>
    api.patch<User>(`/api/admin/users/${id}`, payload),
  auditLogs: (limit = 50) => api.get<AuditLogItem[]>(`/api/admin/audit-logs?limit=${limit}`),
  llmCalls: (limit = 50) => api.get<LlmCallItem[]>(`/api/admin/llm-calls?limit=${limit}`),
  cache: () => api.get<Record<string, number>>('/api/admin/cache')
}
