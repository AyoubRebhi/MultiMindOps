import { Link, useNavigate } from 'react-router-dom';
import StatusBadge from '@/components/common/StatusBadge';
import ProgressBar from '@/components/common/ProgressBar';
import { getWorkflowPhaseMeta } from '@/utils/constants';
import { timeAgo } from '@/utils/formatters';

/**
 * WorkflowCard — summary of a single workflow run with its current phase and
 * progress. The whole card opens the workflow and RESUMES it from its saved
 * phase (/workflows/run/:id); the project name remains an independent link.
 *
 * Progress prefers the explicit completedPhases/totalPhases the backend
 * summary carries, falling back to counting an inline `phases` array (used by
 * the richer per-run views).
 */
export default function WorkflowCard({ workflow, linkToProject = true }) {
  const navigate = useNavigate();
  if (!workflow) return null;
  const {
    id,
    name,
    projectId,
    projectName,
    status,
    currentPhase,
    ownerName,
    updatedAt,
  } = workflow;
  const phase = getWorkflowPhaseMeta(currentPhase);
  const open = () => id && navigate(`/workflows/run/${id}`);
  const onKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      open();
    }
  };

  const inlinePhases = workflow.phases || [];
  const done =
    workflow.completedPhases ??
    inlinePhases.filter((p) => p.status === 'completed').length;
  const total = workflow.totalPhases ?? inlinePhases.length;
  const progress =
    workflow.progress ?? (total > 0 ? Math.round((done / total) * 100) : 0);

  return (
    <div
      className="surface surface-hover h-100"
      role="button"
      tabIndex={0}
      onClick={open}
      onKeyDown={onKeyDown}
      style={{ cursor: 'pointer' }}
      title="Open workflow"
    >
      <div className="d-flex align-items-start justify-content-between mb-2">
        <div>
          <div style={{ fontWeight: 600 }}>{name}</div>
          {projectName &&
            (linkToProject && projectId ? (
              <Link
                to={`/projects/${projectId}`}
                className="card-link"
                style={{ fontSize: '.74rem' }}
                onClick={(e) => e.stopPropagation()}
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
        {ownerName ? (
          <span className="text-muted-3" title="Started by">
            <i className="fa-solid fa-user me-1" />
            {ownerName}
          </span>
        ) : (
          <span className="text-muted-3">
            <i className="fa-solid fa-bolt me-1" />
            {workflow.trigger || '—'}
          </span>
        )}
        <span className="text-muted-3">
          <i className="fa-regular fa-clock me-1" />
          {timeAgo(updatedAt)}
        </span>
      </div>
    </div>
  );
}
