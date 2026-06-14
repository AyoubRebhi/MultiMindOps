import { Link } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import { useAuth } from '@/hooks/useAuth';
import MetricsGrid from '@/components/dashboard/MetricsGrid';
import UsageChartCard from '@/components/dashboard/UsageChartCard';
import LiveActivityCard from '@/components/dashboard/LiveActivityCard';
import RecentProjectsGrid from '@/components/dashboard/RecentProjectsGrid';

/**
 * Dashboard — platform landing page. First page fully backed by the real
 * FastAPI backend (/api/dashboard/*). Each widget fetches independently and
 * owns its loading / empty / success / error+retry states, so a single failing
 * endpoint never blanks the whole page.
 */
export default function Dashboard() {
  const { user } = useAuth();
  const firstName = user?.firstName || user?.name?.split(' ')[0] || 'there';

  return (
    <ContentContainer>
      <PageHeader
        title={`Welcome back, ${firstName} 👋`}
        subtitle="Here's what's happening across your cloud engineering workspace today."
        actions={
          <Link to="/projects" className="bgrd btn px-3 py-2" style={{ fontSize: '.85rem' }}>
            <i className="fa-solid fa-plus me-2" />
            New Project
          </Link>
        }
      />

      {/* KPI cards */}
      <MetricsGrid />

      {/* Trend + activity */}
      <div className="row g-3 mb-4">
        <div className="col-lg-8">
          <UsageChartCard />
        </div>
        <div className="col-lg-4">
          <LiveActivityCard />
        </div>
      </div>

      {/* Recent projects */}
      <RecentProjectsGrid />
    </ContentContainer>
  );
}
