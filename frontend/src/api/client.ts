import type { StreamHandlers, TokenResponse } from '@/types'

const ACCESS_KEY = 'rag.access_token'
const REFRESH_KEY = 'rag.refresh_token'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export function getAccessToken(): string {
  return localStorage.getItem(ACCESS_KEY) || ''
}

export function getRefreshToken(): string {
  return localStorage.getItem(REFRESH_KEY) || ''
}

export function setTokens(tokens: Pick<TokenResponse, 'access_token' | 'refresh_token'>): void {
  localStorage.setItem(ACCESS_KEY, tokens.access_token)
  localStorage.setItem(REFRESH_KEY, tokens.refresh_token)
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

let refreshing: Promise<boolean> | null = null

async function refreshTokens(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false
  if (!refreshing) {
    refreshing = fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh })
    })
      .then(async (res) => {
        if (!res.ok) return false
        const data = (await res.json()) as TokenResponse
        setTokens(data)
        return true
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...(extra || {}) }
  const token = getAccessToken()
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

export async function apiFetch<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = authHeaders(init.headers as Record<string, string>)
  if (!(init.body instanceof FormData) && init.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }
  const response = await fetch(path, { ...init, headers })
  if (response.status === 401 && retry && (await refreshTokens())) {
    return apiFetch<T>(path, init, false)
  }
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail || detail
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, Array.isArray(detail) ? '请求参数不合法' : detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: 'PATCH', body: JSON.stringify(body ?? {}) }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: 'DELETE' }),
  upload: <T>(path: string, form: FormData) => apiFetch<T>(path, { method: 'POST', body: form })
}

function parseEvent(raw: string): { event: string; data: unknown } | null {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return null
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) }
  } catch {
    return null
  }
}

export async function streamChat(
  payload: { conversation_id: string; question: string; use_cache?: boolean },
  handlers: StreamHandlers,
  options: { signal?: AbortSignal; retry?: boolean } = {}
): Promise<void> {
  const retry = options.retry ?? true
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
    signal: options.signal
  })
  if (response.status === 401 && retry && (await refreshTokens())) {
    return streamChat(payload, handlers, { ...options, retry: false })
  }
  if (!response.ok) {
    let detail = '发送失败'
    try {
      const body = await response.json()
      detail = body.detail || detail
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, detail)
  }
  const reader = response.body?.getReader()
  if (!reader) throw new ApiError(500, '浏览器不支持流式响应')
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let index = buffer.indexOf('\n\n')
    while (index >= 0) {
      const chunk = buffer.slice(0, index)
      buffer = buffer.slice(index + 2)
      const parsed = parseEvent(chunk)
      if (parsed) {
        const data = parsed.data as Record<string, unknown>
        if (parsed.event === 'status') handlers.onStatus?.(data as never)
        else if (parsed.event === 'retrieval') handlers.onRetrieval?.(data as never)
        else if (parsed.event === 'delta') handlers.onDelta?.(String(data.text ?? ''))
        else if (parsed.event === 'done') handlers.onDone?.(data)
        else if (parsed.event === 'error') handlers.onError?.(String(data.message ?? '生成失败'))
      }
      index = buffer.indexOf('\n\n')
    }
  }
}
