import { useAuth } from '@/hooks/useAuth';
import Dashboard from './Dashboard';
import AdminDashboardPage from '@/pages/admin/AdminDashboardPage';

/**
 * DashboardRouter — the index route renders the dashboard appropriate to the
 * signed-in role: the workspace overview for Admins, the engineering dashboard
 * for DevOps Engineers.
 */
export default function DashboardRouter() {
  const { isAdmin } = useAuth();
  return isAdmin ? <AdminDashboardPage /> : <Dashboard />;
}
