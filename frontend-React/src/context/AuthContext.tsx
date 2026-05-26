import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import * as authApi from '@/api/auth'
import { onAuthEvent } from '@/api/client'
import { tokenStorage } from '@/lib/tokenStorage'
import { useToast } from '@/components/common/Toast'
import type {
  AuthStatus,
  LoginPayload,
  RegisterPayload,
  UserPublic,
} from '@/types/auth'

interface AuthContextValue {
  user: UserPublic | null
  status: AuthStatus
  isAuthenticated: boolean
  isBootstrapping: boolean
  login: (payload: LoginPayload) => Promise<void>
  register: (payload: RegisterPayload) => Promise<void>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null)
  const [status, setStatus] = useState<AuthStatus>('idle')
  const bootstrapped = useRef(false)
  const toast = useToast()

  // Session restore on first mount.
  useEffect(() => {
    if (bootstrapped.current) return
    bootstrapped.current = true

    if (!tokenStorage.hasRefresh()) {
      setStatus('unauthenticated')
      return
    }

    setStatus('bootstrapping')
    ;(async () => {
      try {
        const me = await authApi.getMe()
        setUser(me)
        setStatus('authenticated')
      } catch {
        // Either refresh failed (interceptor already emitted 'logout') or
        // /me itself failed even after a refresh. Either way: log out.
        tokenStorage.clear()
        setUser(null)
        setStatus('unauthenticated')
      }
    })()
  }, [])

  // React to forced-logout events from the axios interceptor (e.g. refresh
  // token revoked mid-session). Only surface the toast when we were
  // previously authenticated — the very first bootstrap can also fire
  // 'logout' if the stale refresh token is invalid, and showing "session
  // expired" on a cold load is confusing.
  useEffect(() => {
    return onAuthEvent((event) => {
      if (event !== 'logout') return
      setUser((prevUser) => {
        if (prevUser) {
          toast.warning(
            'Session expired',
            'Please sign in again to continue.',
          )
        }
        return null
      })
      setStatus('unauthenticated')
    })
  }, [toast])

  const login = useCallback(async (payload: LoginPayload) => {
    const res = await authApi.login(payload)
    tokenStorage.setPair(res.tokens.access_token, res.tokens.refresh_token)
    setUser(res.user)
    setStatus('authenticated')
  }, [])

  const register = useCallback(async (payload: RegisterPayload) => {
    const res = await authApi.register(payload)
    tokenStorage.setPair(res.tokens.access_token, res.tokens.refresh_token)
    setUser(res.user)
    setStatus('authenticated')
  }, [])

  const logout = useCallback(async () => {
    const refreshToken = tokenStorage.getRefresh()
    try {
      await authApi.logout(refreshToken)
    } catch {
      // Server-side revocation is best-effort. Always clear locally.
    } finally {
      tokenStorage.clear()
      setUser(null)
      setStatus('unauthenticated')
    }
  }, [])

  const refreshUser = useCallback(async () => {
    const me = await authApi.getMe()
    setUser(me)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      status,
      isAuthenticated: status === 'authenticated',
      isBootstrapping: status === 'idle' || status === 'bootstrapping',
      login,
      register,
      logout,
      refreshUser,
    }),
    [user, status, login, register, logout, refreshUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside an <AuthProvider>')
  return ctx
}
