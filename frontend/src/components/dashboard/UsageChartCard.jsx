import Card from '@/components/common/Card';
import AreaChart from '@/components/common/AreaChart';
import Skeleton from '@/components/common/Skeleton';
import EmptyState from '@/components/common/EmptyState';
import WidgetState from './WidgetState';
import { useDashboardUsage, useErrorToast } from '@/hooks/useDashboard';

/**
 * UsageChartCard — last-14-days workflow-run volume. Renders the existing
 * <AreaChart> with real data; shows an empty state when there's no activity in
 * the window (all-zero series) rather than a misleading flat line.
 */
export default function UsageChartCard() {
  const { data, loading, error, refetch } = useDashboardUsage();
  useErrorToast(error, 'Usage chart');

  const hasActivity = !!data && Array.isArray(data.values) && data.values.some((v) => v > 0);

  return (
    <Card
      title="Deployment Volume"
      icon="fa-chart-area"
      action={<span className="text-muted-3" style={{ fontSize: '.75rem' }}>Last 14 days</span>}
    >
      <WidgetState
        loading={loading && !data}
        error={error}
        onRetry={refetch}
        isEmpty={!loading && !!data && !hasActivity}
        errorTitle="Couldn't load usage"
        skeleton={<Skeleton width="100%" height={180} radius={12} />}
        empty={
          <EmptyState
            icon="fa-chart-area"
            title="No runs in the last 14 days"
            message="Workflow activity will plot here once you start a run."
          />
        }
      >
        <AreaChart labels={data?.labels || []} values={data?.values || []} />
      </WidgetState>
    </Card>
  );
}
