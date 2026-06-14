import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import LoadingSpinner from '@/components/common/LoadingSpinner';

/**
 * RoleProtectedRoute — gates a subtree behind both authentication AND a global
 * role (Phase 6). Used for the admin-only surfaces (Members, Invitations, AWS
 * Credentials). A signed-in user without an allowed role is sent to the
 * dashboard rather than the sign-in page — they ARE authenticated, just not
 * authorized for this area.
 *
 * Props:
 *  - roles: string[] — allowed global roles (e.g. ['ADMIN'])
 */
export default function RoleProtectedRoute({ roles = [] }) {
  const { isLoading, isAuthenticated, role } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <LoadingSpinner center label="Authenticating…" />;
  }
  if (!isAuthenticated) {
    return <Navigate to="/auth/signin" replace state={{ from: location }} />;
  }
  if (roles.length > 0 && !roles.includes(role)) {
    return <Navigate to="/" replace />;
  }
  return <Outlet />;
}
