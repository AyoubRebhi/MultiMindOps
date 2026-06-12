import AppRoutes from '@/routes/AppRoutes';

/**
 * Root application component.
 *
 * Providers (Router, Theme) live in main.jsx so App stays a thin shell that
 * simply delegates to the route tree. Add global, always-mounted concerns
 * (toasts, modals, error boundary) here as the platform grows.
 */
export default function App() {
  return <AppRoutes />;
}
