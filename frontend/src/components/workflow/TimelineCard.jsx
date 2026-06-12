import StatusBadge from '@/components/common/StatusBadge';
import { getPhaseMeta } from '@/utils/constants';

/** Map a phase status to a timeline-node modifier + icon. */
function nodeFor(status) {
  switch (status) {
    case 'completed':
      return { cls: 'is-done', icon: 'fa-check' };
    case 'running':
    case 'building':
    case 'provisioning':
      return { cls: 'is-running', icon: 'fa-spinner fa-spin' };
    case 'failed':
    case 'blocked':
    case 'error':
      return { cls: 'is-failed', icon: 'fa-xmark' };
    case 'degraded':
    case 'human_review':
      return { cls: 'is-running', icon: 'fa-exclamation' };
    default:
      return { cls: '', icon: 'fa-circle' };
  }
}

function formatDuration(sec) {
  if (!sec) return null;
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}

/**
 * TimelineCard — vertical phase timeline for a workflow run.
 *
 * Props:
 *  - phases: [{ key, status, durationSec }]
 */
export default function TimelineCard({ phases = [] }) {
  if (!phases.length) {
    return (
      <div className="text-muted-3" style={{ fontSize: '.85rem' }}>
        No phases recorded yet.
      </div>
    );
  }

  return (
    <div className="timeline">
      {phases.map((phase) => {
        const meta = getPhaseMeta(phase.key);
        const node = nodeFor(phase.status);
        const duration = formatDuration(phase.durationSec);
        return (
          <div className="timeline-item" key={phase.key}>
            <span className={`timeline-node ${node.cls}`.trim()}>
              <i className={`fa-solid ${node.icon}`} />
            </span>
            <div className="d-flex align-items-center justify-content-between flex-wrap gap-2">
              <div>
                <div style={{ fontWeight: 600, fontSize: '.875rem' }}>
                  <i
                    className={`${meta.brand ? 'fa-brands' : 'fa-solid'} ${
                      meta.icon
                    } me-2`}
                    style={{ color: 'var(--tx3)', fontSize: '.8rem' }}
                  />
                  {meta.label}
                </div>
                {meta.description && (
                  <div style={{ fontSize: '.76rem', color: 'var(--tx3)' }}>
                    {meta.description}
                  </div>
                )}
              </div>
              <div className="d-flex align-items-center gap-2">
                {duration && (
                  <span style={{ fontSize: '.72rem', color: 'var(--tx3)' }}>
                    {duration}
                  </span>
                )}
                <StatusBadge status={phase.status} />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
