import { Link } from 'react-router-dom';
import StatusBadge from '@/components/common/StatusBadge';
import ProviderBadge from '@/components/common/ProviderBadge';
import ProgressBar from '@/components/common/ProgressBar';
import Tag from '@/components/common/Tag';
import { formatCurrency, timeAgo } from '@/utils/formatters';

/**
 * ProjectCard — summary card for a single project. Links to its detail page.
 * Fully prop-driven; renders whatever subset of fields are present.
 */
export default function ProjectCard({ project }) {
  if (!project) return null;
  const {
    id,
    name,
    description,
    provider,
    environment,
    status,
    progress,
    stack = [],
    services,
    monthlyCost,
    updatedAt,
  } = project;

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
            <div style={{ fontSize: '.72rem', color: 'var(--tx3)' }}>
              {environment}
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
        }}
      >
        {description}
      </p>

      <div className="d-flex flex-wrap gap-2 mb-3">
        <ProviderBadge provider={provider} />
        {stack.slice(0, 3).map((tech) => (
          <Tag key={tech}>{tech}</Tag>
        ))}
      </div>

      <ProgressBar value={progress} showLabel />

      <div
        className="d-flex align-items-center justify-content-between mt-3 pt-3"
        style={{ borderTop: '1px solid var(--bd)', fontSize: '.74rem' }}
      >
        <span className="text-muted-3">
          <i className="fa-solid fa-server me-1" />
          {services} {services === 1 ? 'service' : 'services'}
        </span>
        <span className="text-muted-3">
          {monthlyCost ? formatCurrency(monthlyCost) + '/mo' : 'Not provisioned'}
        </span>
        <span className="text-muted-3">
          <i className="fa-regular fa-clock me-1" />
          {timeAgo(updatedAt)}
        </span>
      </div>
    </Link>
  );
}
