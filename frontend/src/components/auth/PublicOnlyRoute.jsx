import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import LoadingSpinner from '@/components/common/LoadingSpinner';

/**
 * PublicOnlyRoute — the inverse of ProtectedRoute (Phase 6).
 *
 * Wraps the sign-in / sign-up screens so an already-authenticated user who
 * navigates back to them is bounced to the dashboard (which itself routes by
 * role). Keeps the auth pages from being a dead-end for logged-in users.
 */
export default function PublicOnlyRoute() {
  const { isLoading, isAuthenticated } = useAuth();

  if (isLoading) {
    return <LoadingSpinner center label="Loading…" />;
  }
  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }
  return <Outlet />;
}
