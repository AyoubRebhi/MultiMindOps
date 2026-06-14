import { Link } from 'react-router-dom';
import { SkeletonCard } from '@/components/common/Skeleton';
import EmptyState from '@/components/common/EmptyState';
import WidgetState from './WidgetState';
import RecentProjectCard from './RecentProjectCard';
import { useRecentProjects, useErrorToast } from '@/hooks/useDashboard';

/**
 * RecentProjectsGrid — most-recently-updated projects. Shows Name, Status and
 * Last Updated (per spec) plus an optional cost rollup, via <RecentProjectCard>.
 */
export default function RecentProjectsGrid() {
  const { data, loading, error, refetch } = useRecentProjects();
  useErrorToast(error, 'Recent projects');

  const projects = Array.isArray(data) ? data : [];

  return (
    <>
      <div className="d-flex align-items-center justify-content-between mb-3">
        <h2 className="card-title">Recent Projects</h2>
        <Link to="/projects" className="card-link">
          View all <i className="fa-solid fa-arrow-right fa-xs ms-1" />
        </Link>
      </div>

      <WidgetState
        loading={loading && projects.length === 0}
        error={error}
        onRetry={refetch}
        isEmpty={!loading && projects.length === 0}
        errorTitle="Couldn't load projects"
        skeleton={
          <div className="row g-3">
            {[0, 1, 2].map((i) => (
              <div className="col-md-6 col-xl-4" key={i}>
                <SkeletonCard />
              </div>
            ))}
          </div>
        }
        empty={
          <EmptyState
            icon="fa-folder-open"
            title="No projects yet"
            message="Create your first project to start generating infrastructure."
            action={
              <Link to="/projects" className="bgrd btn px-3 py-2" style={{ fontSize: '.85rem' }}>
                <i className="fa-solid fa-plus me-2" />
                New Project
              </Link>
            }
          />
        }
      >
        <div className="row g-3">
          {projects.map((project) => (
            <div className="col-md-6 col-xl-4" key={project.id}>
              <RecentProjectCard project={project} />
            </div>
          ))}
        </div>
      </WidgetState>
    </>
  );
}
