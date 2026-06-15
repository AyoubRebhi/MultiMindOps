import StatusBadge from '@/components/common/StatusBadge';
import { formatDate } from '@/utils/formatters';

/**
 * AnalysisContextHeader — Section A. Project identity + a visually prominent
 * workflow status and the last execution timestamp.
 *
 * The workflow status uses the platform StatusBadge: RUNNING / DONE / FAILED
 * are mapped to the shared lifecycle palette (running / completed / failed).
 *
 * @param {{
 *   project: import('@/types/workflowAnalysis').ProjectInfo,
 *   status: import('@/types/workflowAnalysis').WorkflowAnalysisStatus,
 *   lastUpdated?: string,
 * }} props
 */
const STATUS_TO_LIFECYCLE = { RUNNING: 'running', DONE: 'completed', FAILED: 'failed' };

function shortRepo(url) {
  if (!url) return null;
  return url.replace(/^https?:\/\/(www\.)?/i, '').replace(/\.git$/i, '');
}

export default function AnalysisContextHeader({ project, status, lastUpdated }) {
  const p = project || {};
  const lifecycle = STATUS_TO_LIFECYCLE[status] || 'pending';

  return (
    <div className="surface project-summary mb-3">
      <div className="d-flex align-items-start justify-content-between flex-wrap gap-3">
        <div className="d-flex align-items-center gap-3" style={{ minWidth: 0 }}>
          <div className="project-summary-logo">
            <i className={`${p.brandIcon ? 'fa-brands' : 'fa-solid'} ${p.logoIcon || 'fa-cube'}`} />
          </div>
          <div style={{ minWidth: 0 }}>
            <h2 className="project-summary-name">{p.name || 'Untitled project'}</h2>
            {p.repositoryUrl && (
              <a
                href={p.repositoryUrl}
                target="_blank"
                rel="noreferrer"
                className="project-summary-repo"
              >
                <i className="fa-brands fa-github me-1" />
                {shortRepo(p.repositoryUrl)}
              </a>
            )}
          </div>
        </div>

        {/* Visually prominent status */}
        <div className="d-flex flex-column align-items-end gap-2">
          <StatusBadge status={lifecycle} className="badge-lg" />
          <span className="text-muted-3" style={{ fontSize: '.74rem' }}>
            <i className="fa-regular fa-clock me-1" />
            Last execution: {lastUpdated ? formatDate(lastUpdated) : '—'}
          </span>
        </div>
      </div>

      <div className="summary-grid">
        <HeaderItem icon="fa-fingerprint" label="Project ID" value={p.id || '—'} mono />
        {p.branch && <HeaderItem icon="fa-code-branch" label="Branch" value={p.branch} />}
        <HeaderItem icon="fa-wand-magic-sparkles" label="Stage" value="Workflow Analysis" />
      </div>
    </div>
  );
}

function HeaderItem({ icon, label, value, mono = false }) {
  return (
    <div className="summary-item">
      <span className="summary-item-ico"><i className={`fa-solid ${icon}`} /></span>
      <div style={{ minWidth: 0 }}>
        <div className="summary-item-label">{label}</div>
        <div className={`summary-item-value ${mono ? 'mono' : ''}`.trim()}>{value}</div>
      </div>
    </div>
  );
}
