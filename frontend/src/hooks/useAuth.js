import { useContext } from 'react';
import { AuthContext } from '@/context/AuthContext';

/** Access the backend-driven auth session: current user, role/workspace,
 *  status flags (isLoading/isAuthenticated/isAdmin) and auth actions
 *  (login/logout/register/refreshUser). */
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an <AuthProvider>');
  return ctx;
}
