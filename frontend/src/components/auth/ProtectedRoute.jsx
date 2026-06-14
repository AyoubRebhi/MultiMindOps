import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import LoadingSpinner from '@/components/common/LoadingSpinner';

/**
 * ProtectedRoute — gates a subtree behind authentication (Phase 6).
 *
 * While the session is still resolving (`/auth/me` in flight) we show a
 * spinner rather than flashing the sign-in page. Unauthenticated users are
 * redirected to sign-in, preserving the attempted location in router state so
 * the sign-in page can send them back after a successful login.
 */
export default function ProtectedRoute() {
  const { isLoading, isAuthenticated, mustChangePassword } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <LoadingSpinner center label="Authenticating…" />;
  }
  if (!isAuthenticated) {
    return <Navigate to="/auth/signin" replace state={{ from: location }} />;
  }
  // Forced password change (Phase 7): an invited engineer signing in with a
  // temporary password must set their own before reaching anything else.
  if (mustChangePassword && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />;
  }
  return <Outlet />;
}
