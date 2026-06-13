import StatusBadge from '@/components/common/StatusBadge';

/**
 * PipelineStageCard — one high-level pipeline stage (Section 4 of the Execution
 * Center). Shows the stage name + status, its start/end time and duration, and
 * the artifacts it produced. Colored by status (success / failed / running /
 * skipped). Render a grid of these from the stage list.
 *
 * Props:
 *  - stage: { key, name, icon, brand, status, startTime, endTime, duration, artifacts[] }
 */
const STATUS_RAIL = {
  success: 'completed',
  failed: 'failed',
  running: 'running',
  pending: 'pending',
  skipped: 'not_started',
};

export default function PipelineStageCard({ stage }) {
  if (!stage) return null;
  const railStatus = STATUS_RAIL[stage.status] || 'pending';

  return (
    <div className={`surface stage-card rail-${railStatus}`}>
      <div className="stage-card-head">
        <span className={`stage-ico stage-ico-${stage.status}`}>
          <i className={`${stage.brand ? 'fa-brands' : 'fa-solid'} ${stage.icon}`} />
        </span>
        <div style={{ minWidth: 0 }}>
          <div className="stage-name">{stage.name}</div>
          <div className="stage-time">
            <i className="fa-solid fa-stopwatch me-1" />
            {stage.duration}
          </div>
        </div>
        <StatusBadge status={railStatus} className="ms-auto" />
      </div>

      <div className="stage-times">
        <div className="stage-time-item">
          <span className="stage-time-label">Start</span>
          <span className="stage-time-val mono">{stage.startTime}</span>
        </div>
        <div className="stage-time-item">
          <span className="stage-time-label">End</span>
          <span className="stage-time-val mono">{stage.endTime}</span>
        </div>
      </div>

      <div className="stage-artifacts">
        <span className="stage-artifacts-label">
          <i className="fa-solid fa-box-archive me-1" />
          Artifacts
        </span>
        {stage.artifacts && stage.artifacts.length > 0 ? (
          <div className="d-flex flex-wrap gap-1 mt-1">
            {stage.artifacts.map((a) => (
              <span className="tag mono" key={a}>{a}</span>
            ))}
          </div>
        ) : (
          <span className="stage-artifacts-none">—</span>
        )}
      </div>
    </div>
  );
}
