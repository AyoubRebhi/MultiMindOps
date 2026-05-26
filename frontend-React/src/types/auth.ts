// ─── Auth types ───────────────────────────────────────────────────────────────
// Mirrors backend/app/schemas/auth.py — keep in sync.

export interface UserPublic {
  id: string
  email: string
  display_name: string | null
  avatar_url: string | null
  auth_provider: string
  email_verified: string
  account_status: string
  last_login_at: string | null
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface AuthSuccessResponse {
  user: UserPublic
  tokens: TokenPair
}

export interface LoginPayload {
  email: string
  password: string
}

export interface RegisterPayload {
  email: string
  password: string
  display_name?: string
}

export type AuthStatus =
  | 'idle'          // initial — before bootstrap
  | 'bootstrapping' // restoring session from storage
  | 'authenticated'
  | 'unauthenticated'
