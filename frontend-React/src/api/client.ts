import axios, { AxiosError, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'
import { tokenStorage } from '@/lib/tokenStorage'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 120_000, // 2 min — LLM calls can be slow
})

// ─── Auth event bus ──────────────────────────────────────────────────────────
// AuthContext subscribes to these instead of the interceptor reaching into
// React state directly. Keeps the interceptor decoupled from the provider.
type AuthEvent = 'logout' | 'tokens-updated'
type AuthListener = (event: AuthEvent) => void

const listeners = new Set<AuthListener>()

export function onAuthEvent(listener: AuthListener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function emit(event: AuthEvent): void {
  for (const l of listeners) {
    try { l(event) } catch { /* ignore listener errors */ }
  }
}

// ─── Refresh coordination ────────────────────────────────────────────────────
// One in-flight refresh at a time. Concurrent 401s queue on the same promise.
let refreshPromise: Promise<string | null> | null = null

async function performRefresh(): Promise<string | null> {
  const refreshToken = tokenStorage.getRefresh()
  if (!refreshToken) return null

  // Lazy import to avoid a circular module load at startup.
  const { refresh } = await import('./auth')
  try {
    const res = await refresh(refreshToken)
    tokenStorage.setPair(res.tokens.access_token, res.tokens.refresh_token)
    emit('tokens-updated')
    return res.tokens.access_token
  } catch {
    tokenStorage.clear()
    emit('logout')
    return null
  }
}

function getOrStartRefresh(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = performRefresh().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

// ─── Request interceptor: attach bearer ──────────────────────────────────────
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokenStorage.getAccess()
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ─── Response interceptor: silent refresh + retry on 401 ─────────────────────
interface RetryableConfig extends AxiosRequestConfig {
  _retried?: boolean
}

apiClient.interceptors.response.use(
  (res) => res,
  async (err: AxiosError) => {
    const original = err.config as RetryableConfig | undefined
    const status = err.response?.status

    // Don't try to refresh on the auth endpoints themselves — a 401 on
    // /login or /refresh is a real failure, not a stale-token signal.
    const url = original?.url ?? ''
    const isAuthEndpoint = url.includes('/api/auth/')

    if (status === 401 && original && !original._retried && !isAuthEndpoint && tokenStorage.hasRefresh()) {
      original._retried = true
      const newToken = await getOrStartRefresh()
      if (newToken) {
        original.headers = { ...(original.headers ?? {}), Authorization: `Bearer ${newToken}` }
        return apiClient.request(original)
      }
      // refresh failed — emit('logout') already fired in performRefresh
    } else if (status === 401 && !isAuthEndpoint && !tokenStorage.hasRefresh()) {
      // No refresh available — surface as logged-out so the UI redirects.
      emit('logout')
    }

    // Normalize error message for call-sites.
    const message =
      (err.response?.data as { detail?: string; message?: string } | undefined)?.detail ??
      (err.response?.data as { detail?: string; message?: string } | undefined)?.message ??
      err.message ??
      'An unexpected error occurred'
    const normalized = new Error(String(message)) as Error & { status?: number }
    normalized.status = status
    return Promise.reject(normalized)
  },
)
