import { Link } from 'react-router-dom';
import StatusBadge from '@/components/common/StatusBadge';
import ProgressBar from '@/components/common/ProgressBar';
import { getPhaseMeta } from '@/utils/constants';
import { timeAgo } from '@/utils/formatters';

/**
 * WorkflowCard — summary of a single workflow run with its current phase and
 * progress. Optionally links back to the owning project.
 */
export default function WorkflowCard({ workflow, linkToProject = true }) {
  if (!workflow) return null;
  const {
    name,
    projectId,
    projectName,
    status,
    currentPhase,
    progress,
    trigger,
    updatedAt,
  } = workflow;
  const phase = getPhaseMeta(currentPhase);
  const done = (workflow.phases || []).filter(
    (p) => p.status === 'completed'
  ).length;
  const total = (workflow.phases || []).length;

  return (
    <div className="surface surface-hover h-100">
      <div className="d-flex align-items-start justify-content-between mb-2">
        <div>
          <div style={{ fontWeight: 600 }}>{name}</div>
          {projectName &&
            (linkToProject ? (
              <Link
                to={`/projects/${projectId}`}
                className="card-link"
                style={{ fontSize: '.74rem' }}
              >
                {projectName}
              </Link>
            ) : (
              <div style={{ fontSize: '.74rem', color: 'var(--tx3)' }}>
                {projectName}
              </div>
            ))}
        </div>
        <StatusBadge status={status} />
      </div>

      <div
        className="d-flex align-items-center gap-2 mb-3"
        style={{ fontSize: '.8rem', color: 'var(--tx2)' }}
      >
        <i
          className={`${phase.brand ? 'fa-brands' : 'fa-solid'} ${phase.icon}`}
          style={{ color: '#a78bfa' }}
        />
        <span>{phase.label}</span>
        <span className="text-muted-3">
          · {done}/{total} phases
        </span>
      </div>

      <ProgressBar value={progress} showLabel />

      <div
        className="d-flex align-items-center justify-content-between mt-3 pt-3"
        style={{ borderTop: '1px solid var(--bd)', fontSize: '.74rem' }}
      >
        <span className="text-muted-3">
          <i className="fa-solid fa-bolt me-1" />
          {trigger}
        </span>
        <span className="text-muted-3">
          <i className="fa-regular fa-clock me-1" />
          {timeAgo(updatedAt)}
        </span>
      </div>
    </div>
  );
}
