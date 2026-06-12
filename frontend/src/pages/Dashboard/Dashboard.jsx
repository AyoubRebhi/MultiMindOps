import { Link } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import StatsCard from '@/components/common/StatsCard';
import Card from '@/components/common/Card';
import AreaChart from '@/components/common/AreaChart';
import ActivityFeed from '@/components/common/ActivityFeed';
import ProjectCard from '@/components/projects/ProjectCard';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { useAsync } from '@/hooks/useAsync';
import { useProjects } from '@/hooks/useProjects';
import { useAuth } from '@/hooks/useAuth';
import { dashboardApi } from '@/services/api/dashboardApi';

/**
 * Dashboard — platform landing page. Headline KPIs, the deployments trend,
 * a live activity feed and a peek at recent projects. All data via mock API.
 */
export default function Dashboard() {
  const { data: summary, loading } = useAsync(() => dashboardApi.getSummary());
  const { data: projects } = useProjects();
  const { user } = useAuth();

  const recentProjects = (projects || []).slice(0, 3);
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

      {loading && !summary ? (
        <LoadingSpinner center label="Loading dashboard…" />
      ) : (
        <>
          {/* KPI cards */}
          <div className="row g-3 mb-4">
            {(summary?.stats || []).map((stat) => (
              <div className="col-6 col-xl-3" key={stat.id}>
                <StatsCard
                  label={stat.label}
                  value={stat.value}
                  delta={stat.delta}
                  trend={stat.trend}
                  icon={stat.icon}
                  accent={stat.accent}
                  gradientValue={stat.id === 'projects'}
                />
              </div>
            ))}
          </div>

          {/* Trend + activity */}
          <div className="row g-3 mb-4">
            <div className="col-lg-8">
              <Card
                title="Deployment Volume"
                icon="fa-chart-area"
                action={<span className="text-muted-3" style={{ fontSize: '.75rem' }}>Last 14 days</span>}
              >
                <AreaChart
                  labels={summary?.trend?.labels || []}
                  values={summary?.trend?.values || []}
                />
              </Card>
            </div>
            <div className="col-lg-4">
              <Card
                title="Live Activity"
                action={
                  <span className="badge-pill badge-success">
                    <span className="dot" /> Live
                  </span>
                }
                bodyClassName=""
              >
                <ActivityFeed items={summary?.activity || []} max={5} />
              </Card>
            </div>
          </div>

          {/* Recent projects */}
          <div className="d-flex align-items-center justify-content-between mb-3">
            <h2 className="card-title">Recent Projects</h2>
            <Link to="/projects" className="card-link">
              View all <i className="fa-solid fa-arrow-right fa-xs ms-1" />
            </Link>
          </div>
          <div className="row g-3">
            {recentProjects.map((project) => (
              <div className="col-md-6 col-xl-4" key={project.id}>
                <ProjectCard project={project} />
              </div>
            ))}
          </div>
        </>
      )}
    </ContentContainer>
  );
}
