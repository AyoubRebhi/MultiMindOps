import axios from 'axios'
import { apiClient } from './client'
import type {
  AuthSuccessResponse,
  LoginPayload,
  RegisterPayload,
  UserPublic,
} from '@/types/auth'

// Raw axios instance for refresh — bypasses our interceptors so a 401 on
// the refresh endpoint itself doesn't trigger a recursive refresh attempt.
const rawClient = axios.create({
  baseURL: apiClient.defaults.baseURL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
})

// Match the normalize-error behavior used by apiClient.
rawClient.interceptors.response.use(
  (res) => res,
  (err) => {
    const message =
      err.response?.data?.detail ??
      err.response?.data?.message ??
      err.message ??
      'An unexpected error occurred'
    return Promise.reject(new Error(String(message)))
  },
)

export async function login(payload: LoginPayload): Promise<AuthSuccessResponse> {
  const { data } = await apiClient.post<AuthSuccessResponse>('/api/auth/login', payload)
  return data
}

export async function register(payload: RegisterPayload): Promise<AuthSuccessResponse> {
  const { data } = await apiClient.post<AuthSuccessResponse>('/api/auth/register', payload)
  return data
}

export async function refresh(refreshToken: string): Promise<AuthSuccessResponse> {
  // Uses rawClient so the response interceptor doesn't try to "refresh the
  // refresh" — that's the infinite-loop trap.
  const { data } = await rawClient.post<AuthSuccessResponse>('/api/auth/refresh', {
    refresh_token: refreshToken,
  })
  return data
}

export async function logout(refreshToken?: string | null): Promise<void> {
  // Best-effort: server-side revocation. If it fails (e.g. token already
  // dead) we still clear locally — that's handled by the AuthContext.
  await apiClient.post('/api/auth/logout', refreshToken ? { refresh_token: refreshToken } : {})
}

export async function getMe(): Promise<UserPublic> {
  const { data } = await apiClient.get<UserPublic>('/api/auth/me')
  return data
}
