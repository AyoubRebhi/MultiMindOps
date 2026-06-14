import Card from '@/components/common/Card';
import ActivityFeed from '@/components/common/ActivityFeed';
import EmptyState from '@/components/common/EmptyState';
import Skeleton from '@/components/common/Skeleton';
import WidgetState from './WidgetState';
import { useLiveActivity, useErrorToast } from '@/hooks/useDashboard';

/**
 * LiveActivityCard — merged feed of recent workflow events, project and
 * artifact activity. Reuses the existing <ActivityFeed>; the backend already
 * returns feed-shaped items ({ id, type, icon, message, at }).
 */
export default function LiveActivityCard() {
  const { data, loading, error, refetch } = useLiveActivity();
  useErrorToast(error, 'Live activity');

  const items = Array.isArray(data) ? data : [];

  return (
    <Card
      title="Live Activity"
      action={
        <span className="badge-pill badge-success">
          <span className="dot" /> Live
        </span>
      }
    >
      <WidgetState
        loading={loading && items.length === 0}
        error={error}
        onRetry={refetch}
        isEmpty={!loading && items.length === 0}
        errorTitle="Couldn't load activity"
        skeleton={<ActivitySkeleton />}
        empty={
          <EmptyState
            icon="fa-wave-square"
            title="No recent activity"
            message="Events from your workflows will appear here in real time."
          />
        }
      >
        <ActivityFeed items={items} max={5} />
      </WidgetState>
    </Card>
  );
}

function ActivitySkeleton() {
  return (
    <div className="d-flex flex-column gap-2">
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="d-flex gap-3 align-items-center"
          style={{ padding: '10px 12px', background: 'var(--bg3)', borderRadius: 10 }}
        >
          <Skeleton width="30px" height={30} radius={8} />
          <div style={{ flex: 1 }}>
            <Skeleton width="85%" height={12} />
            <Skeleton width="40%" height={10} className="mt-2" />
          </div>
        </div>
      ))}
    </div>
  );
}
