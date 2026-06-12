import { createContext, useCallback, useEffect, useMemo, useState } from 'react';
import { authApi } from '@/services/api/authApi';
import { mockCurrentUser, mockEngineerUser } from '@/services/mock/mockCurrentUser';
import { ROLES } from '@/utils/constants';

/**
 * AuthContext — MOCK auth/session state for the demo.
 *
 * This deliberately does NOT implement real authentication, JWT handling or
 * authorization guards (out of scope for this UI phase). It just holds the
 * "signed-in" user so the layout/sidebar can react to role, and exposes the
 * mock auth actions the auth pages call. The session is seeded as an
 * authenticated Admin so the platform is immediately explorable; the role is
 * persisted to localStorage so a refresh keeps your place.
 */
// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext(null);

const STORAGE_KEY = 'cloudforge.auth';

function loadSession() {
  if (typeof window === 'undefined') return { user: mockCurrentUser, isAuthenticated: true };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed?.user) return { user: parsed.user, isAuthenticated: parsed.isAuthenticated ?? true };
    }
  } catch {
    /* ignore corrupt storage */
  }
  return { user: mockCurrentUser, isAuthenticated: true };
}

export function AuthProvider({ children }) {
  const [{ user, isAuthenticated }, setSession] = useState(loadSession);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ user, isAuthenticated }));
    } catch {
      /* ignore */
    }
  }, [user, isAuthenticated]);

  const signIn = useCallback(async (credentials) => {
    const { user: next } = await authApi.signIn(credentials);
    setSession({ user: next, isAuthenticated: true });
    return next;
  }, []);

  const signUp = useCallback(async (payload) => {
    const { user: next } = await authApi.signUp(payload);
    setSession({ user: next, isAuthenticated: true });
    return next;
  }, []);

  const completeRegistration = useCallback(async (token, payload) => {
    const { user: next } = await authApi.completeRegistration(token, payload);
    setSession({ user: next, isAuthenticated: true });
    return next;
  }, []);

  const signOut = useCallback(async () => {
    await authApi.signOut();
    setSession((prev) => ({ ...prev, isAuthenticated: false }));
  }, []);

  /** Demo-only helper: jump between the Admin and DevOps Engineer experiences. */
  const switchRole = useCallback((role) => {
    setSession({
      user: role === ROLES.DEVOPS_ENGINEER ? mockEngineerUser : mockCurrentUser,
      isAuthenticated: true,
    });
  }, []);

  /** Update the in-memory user (e.g. after editing profile / creating a workspace). */
  const updateUser = useCallback((changes) => {
    setSession((prev) => ({ ...prev, user: { ...prev.user, ...changes } }));
  }, []);

  const value = useMemo(
    () => ({
      user,
      isAuthenticated,
      isAdmin: user?.role === ROLES.ADMIN,
      signIn,
      signUp,
      signOut,
      completeRegistration,
      switchRole,
      updateUser,
    }),
    [user, isAuthenticated, signIn, signUp, signOut, completeRegistration, switchRole, updateUser]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
