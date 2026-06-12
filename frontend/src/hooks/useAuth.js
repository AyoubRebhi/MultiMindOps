import { useContext } from 'react';
import { AuthContext } from '@/context/AuthContext';

/** Access the (mock) auth session: current user, role flags and auth actions. */
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an <AuthProvider>');
  return ctx;
}
