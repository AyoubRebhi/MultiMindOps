import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import SessionLoadingPage from '@/pages/SessionLoadingPage'

/**
 * Gate for authenticated routes.
 *
 * - while bootstrapping: render the loading splash so we don't
 *   redirect away before the session is restored
 * - if unauthenticated: redirect to /login, preserving the intended
 *   destination on location.state.from so post-login can return there
 */
export function ProtectedRoute() {
  const { isAuthenticated, isBootstrapping } = useAuth()
  const location = useLocation()

  if (isBootstrapping) return <SessionLoadingPage />

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return <Outlet />
}
