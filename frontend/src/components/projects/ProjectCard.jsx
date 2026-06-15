import { Link } from 'react-router-dom';
import StatusBadge from '@/components/common/StatusBadge';
import { ProjectAnalysisStatusBadge } from '@/components/projects/ProjectAnalysisStatus';
import { timeAgo } from '@/utils/formatters';

/** Strip the scheme so a long GitHub URL reads compactly on the card. */
function shortRepo(url) {
  if (!url) return null;
  return url.replace(/^https?:\/\/(www\.)?/i, '').replace(/\.git$/i, '');
}

/**
 * ProjectCard — summary card for a single (real) project. Prop-driven off the
 * mapped ProjectResponse shape; links to the detail page.
 */
export default function ProjectCard({ project }) {
  if (!project) return null;
  const {
    id,
    name,
    description,
    repositoryUrl,
    repositoryVisibility,
    status,
    bootstrapStatus,
    updatedAt,
  } = project;

  return (
    <Link to={`/projects/${id}`} className="surface surface-hover d-block h-100">
      <div className="d-flex align-items-start justify-content-between mb-2">
        <div className="d-flex align-items-center gap-2" style={{ minWidth: 0 }}>
          <div className="icon-tile" style={{ background: 'rgba(139,92,246,.15)', color: '#a78bfa' }}>
            <i className="fa-solid fa-cube" />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {name}
            </div>
            <div style={{ fontSize: '.72rem', color: 'var(--tx3)' }}>
              <i className={`fa-solid ${repositoryVisibility === 'private' ? 'fa-lock' : 'fa-globe'} me-1`} />
              {repositoryVisibility || 'public'}
            </div>
          </div>
        </div>
        <StatusBadge status={status} />
      </div>

      <p
        style={{
          fontSize: '.82rem',
          color: 'var(--tx2)',
          margin: '4px 0 14px',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
          minHeight: 38,
        }}
      >
        {description || 'No description provided.'}
      </p>

      {repositoryUrl && (
        <div
          className="mono mb-3 d-flex align-items-center gap-2"
          style={{ fontSize: '.74rem', color: 'var(--tx3)', overflow: 'hidden' }}
        >
          <i className="fa-brands fa-github" />
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {shortRepo(repositoryUrl)}
          </span>
        </div>
      )}

      <div
        className="d-flex align-items-center justify-content-between mt-3 pt-3"
        style={{ borderTop: '1px solid var(--bd)', fontSize: '.74rem' }}
      >
        <ProjectAnalysisStatusBadge status={bootstrapStatus} />
        <span className="text-muted-3">
          <i className="fa-regular fa-clock me-1" />
          {timeAgo(updatedAt)}
        </span>
      </div>
    </Link>
  );
}
