import { Link } from 'react-router-dom';
import StatusBadge from '@/components/common/StatusBadge';
import { formatCurrency, timeAgo } from '@/utils/formatters';

/**
 * RecentProjectCard — compact project tile for the dashboard's Recent Projects
 * grid. Unlike the full <ProjectCard> (mock-rich), this renders ONLY fields the
 * backend authentically provides for a project — name, status, last-updated and
 * (when estimated) monthly cost — so nothing is fabricated. Shares the same
 * `surface` design-system styling for visual consistency.
 */
export default function RecentProjectCard({ project }) {
  if (!project) return null;
  const { id, name, description, status, monthlyCost, updatedAt, architectureType } = project;

  return (
    <Link to={`/projects/${id}`} className="surface surface-hover d-block h-100">
      <div className="d-flex align-items-start justify-content-between mb-2">
        <div className="d-flex align-items-center gap-2">
          <div
            className="icon-tile"
            style={{ background: 'rgba(139,92,246,.15)', color: '#a78bfa' }}
          >
            <i className="fa-solid fa-cube" />
          </div>
          <div>
            <div style={{ fontWeight: 600 }}>{name}</div>
            {architectureType && (
              <div style={{ fontSize: '.72rem', color: 'var(--tx3)' }}>{architectureType}</div>
            )}
          </div>
        </div>
        <StatusBadge status={status} />
      </div>

      {description && (
        <p
          style={{
            fontSize: '.82rem',
            color: 'var(--tx2)',
            margin: '4px 0 14px',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
          }}
        >
          {description}
        </p>
      )}

      <div
        className="d-flex align-items-center justify-content-between mt-3 pt-3"
        style={{ borderTop: '1px solid var(--bd)', fontSize: '.74rem' }}
      >
        <span className="text-muted-3">
          {monthlyCost != null ? `${formatCurrency(monthlyCost)}/mo` : 'Not provisioned'}
        </span>
        <span className="text-muted-3">
          <i className="fa-regular fa-clock me-1" />
          {timeAgo(updatedAt)}
        </span>
      </div>
    </Link>
  );
}
