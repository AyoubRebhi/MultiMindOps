import StatsCard from '@/components/common/StatsCard';
import Skeleton from '@/components/common/Skeleton';
import EmptyState from '@/components/common/EmptyState';
import WidgetState from './WidgetState';
import { useDashboardMetrics, useErrorToast } from '@/hooks/useDashboard';

/**
 * MetricsGrid — the four KPI tiles (Active Projects, Running Workflows,
 * Pipeline Success %, Monthly Cloud Spend). Loads independently with its own
 * loading skeleton, error+retry and empty fallback.
 */
export default function MetricsGrid() {
  const { data: stats, loading, error, refetch } = useDashboardMetrics();
  useErrorToast(error, 'Dashboard metrics');

  return (
    <div className="row g-3 mb-4">
      <WidgetState
        loading={loading && !stats}
        error={error}
        onRetry={refetch}
        isEmpty={!loading && Array.isArray(stats) && stats.length === 0}
        errorTitle="Couldn't load metrics"
        skeleton={<MetricsSkeleton />}
        empty={
          <div className="col-12">
            <EmptyState icon="fa-chart-simple" title="No metrics yet" message="Metrics appear once you create a project." />
          </div>
        }
      >
        {(stats || []).map((stat) => (
          <div className="col-6 col-xl-3" key={stat.id}>
            <StatsCard
              label={stat.label}
              value={stat.value}
              delta={stat.delta}
              trend={stat.trend}
              icon={stat.icon}
              accent={stat.accent}
              gradientValue={stat.gradientValue}
            />
          </div>
        ))}
      </WidgetState>
    </div>
  );
}

function MetricsSkeleton() {
  return (
    <>
      {[0, 1, 2, 3].map((i) => (
        <div className="col-6 col-xl-3" key={i}>
          <div className="db-stat-card">
            <Skeleton width="42px" height={42} radius={12} />
            <Skeleton width="50%" height={26} className="mt-3" />
            <Skeleton width="70%" height={12} className="mt-2" />
          </div>
        </div>
      ))}
    </>
  );
}
