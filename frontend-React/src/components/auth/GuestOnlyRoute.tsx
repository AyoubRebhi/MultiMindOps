import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import SessionLoadingPage from '@/pages/SessionLoadingPage'

interface LocationState {
  from?: { pathname?: string }
}

/**
 * Inverse of ProtectedRoute — for /login and /register.
 *
 * If the user lands here while already authenticated (e.g. opens /login
 * in a second tab), send them onward instead of showing the form. We
 * respect location.state.from so a deep-link → login → resume flow
 * lands back where they started.
 */
export function GuestOnlyRoute() {
  const { isAuthenticated, isBootstrapping } = useAuth()
  const location = useLocation()

  if (isBootstrapping) return <SessionLoadingPage />

  if (isAuthenticated) {
    const state = location.state as LocationState | null
    const target = state?.from?.pathname ?? '/'
    return <Navigate to={target} replace />
  }

  return <Outlet />
}
