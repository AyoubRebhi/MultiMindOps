import { createContext, useCallback, useEffect, useMemo, useState } from 'react';
import { authApi, normalizeUser } from '@/services/api/authApi';
import { tokenStore } from '@/services/api/tokenStore';
import { ROLES } from '@/utils/constants';

/**
 * AuthContext — REAL, backend-driven session state (Phase 3).
 *
 * Lifecycle / status:
 *   'loading'         — bootstrapping: a token exists and /auth/me is in flight
 *   'authenticated'   — a current user is loaded
 *   'unauthenticated' — no token, or the token/refresh failed
 *
 * The token pair lives in tokenStore (localStorage); the Axios client injects
 * it and transparently refreshes on 401. When refresh ultimately fails the
 * client dispatches `auth:session-expired`, which we listen for here to drop
 * the in-memory user (expired-session handling).
 *
 * Exposes: currentUser, role, workspace, login(), logout(), register(),
 * refreshUser(), plus isAuthenticated / isAdmin / isLoading flags. The legacy
 * `signIn`/`signUp`/`signOut` names are kept as aliases for existing callers.
 */
// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState('loading'); // loading | authenticated | unauthenticated

  // ── Bootstrap: resolve the session from a persisted token on first mount ──
  useEffect(() => {
    let active = true;
    async function bootstrap() {
      if (!tokenStore.has()) {
        if (active) setStatus('unauthenticated');
        return;
      }
      try {
        const apiUser = await authApi.getCurrentUser();
        if (!active) return;
        setUser(normalizeUser(apiUser));
        setStatus('authenticated');
      } catch {
        // Token invalid/expired and unrefreshable — start clean.
        if (!active) return;
        tokenStore.clear();
        setUser(null);
        setStatus('unauthenticated');
      }
    }
    bootstrap();
    return () => {
      active = false;
    };
  }, []);

  // ── Expired-session handling: the Axios client tells us a refresh failed ──
  useEffect(() => {
    const onExpired = () => {
      setUser(null);
      setStatus('unauthenticated');
    };
    window.addEventListener('auth:session-expired', onExpired);
    return () => window.removeEventListener('auth:session-expired', onExpired);
  }, []);

  const login = useCallback(async (credentials) => {
    const { user: apiUser, tokens } = await authApi.signIn(credentials);
    tokenStore.set(tokens);
    const next = normalizeUser(apiUser);
    setUser(next);
    setStatus('authenticated');
    return next;
  }, []);

  const register = useCallback(async (payload) => {
    const { user: apiUser, tokens } = await authApi.signUp(payload);
    tokenStore.set(tokens);
    const next = normalizeUser(apiUser);
    setUser(next);
    setStatus('authenticated');
    return next;
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.signOut({ refresh_token: tokenStore.getRefresh() });
    } catch {
      /* best-effort — log out locally regardless */
    }
    tokenStore.clear();
    setUser(null);
    setStatus('unauthenticated');
  }, []);

  const refreshUser = useCallback(async () => {
    const apiUser = await authApi.getCurrentUser();
    const next = normalizeUser(apiUser);
    setUser(next);
    setStatus('authenticated');
    return next;
  }, []);

  /** Change the current user's password. Also clears a forced-change
   *  requirement (invited engineers) — the backend returns the refreshed user
   *  with must_change_password=false, which we reflect in state. */
  const changePassword = useCallback(async ({ currentPassword, newPassword }) => {
    const apiUser = await authApi.changePassword({ currentPassword, newPassword });
    const next = normalizeUser(apiUser);
    setUser(next);
    setStatus('authenticated');
    return next;
  }, []);

  /** Merge changes into the in-memory user (e.g. after a profile edit). Does
   *  not persist on its own — callers that hit the backend should follow with
   *  refreshUser() to reconcile. */
  const updateUser = useCallback((changes) => {
    setUser((prev) => (prev ? { ...prev, ...changes } : prev));
  }, []);

  const value = useMemo(
    () => ({
      user,
      currentUser: user,
      role: user?.role || null,
      workspace: user?.workspace || null,
      status,
      isLoading: status === 'loading',
      isAuthenticated: status === 'authenticated',
      isAdmin: user?.role === ROLES.ADMIN,
      mustChangePassword: !!user?.mustChangePassword,
      login,
      logout,
      register,
      refreshUser,
      changePassword,
      updateUser,
      // Backward-compatible aliases for existing components.
      signIn: login,
      signUp: register,
      signOut: logout,
    }),
    [user, status, login, logout, register, refreshUser, changePassword, updateUser]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
