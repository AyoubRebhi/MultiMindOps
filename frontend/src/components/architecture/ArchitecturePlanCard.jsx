import { Link } from 'react-router-dom';
import StatusBadge from '@/components/common/StatusBadge';
import ProviderBadge from '@/components/common/ProviderBadge';
import { formatCurrency } from '@/utils/formatters';

/**
 * ArchitecturePlanCard — a proposed architecture with its recommended option,
 * key components and estimated cost.
 *
 * Props:
 *  - plan: see mockArchitecturePlans shape
 *  - linkToProject: render the project name as a link (default true)
 */
export default function ArchitecturePlanCard({ plan, linkToProject = true }) {
  if (!plan) return null;
  const {
    title,
    provider,
    status,
    summary,
    estimatedCost,
    components = [],
    options = [],
    projectId,
    projectName,
  } = plan;
  const recommended = options.find((o) => o.recommended);

  return (
    <div className="surface surface-hover h-100 d-flex flex-column">
      <div className="d-flex align-items-start justify-content-between mb-2">
        <div>
          <div style={{ fontWeight: 600 }}>{title}</div>
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

      <p style={{ fontSize: '.82rem', color: 'var(--tx2)', margin: '4px 0 14px' }}>
        {summary}
      </p>

      <div className="d-flex flex-wrap gap-2 mb-3">
        {components.map((c) => (
          <span className="tag" key={c.name}>
            <i className={`fa-solid ${c.icon}`} style={{ color: '#a78bfa' }} />
            {c.name}
          </span>
        ))}
      </div>

      <div
        className="d-flex align-items-center justify-content-between mt-auto pt-3"
        style={{ borderTop: '1px solid var(--bd)' }}
      >
        <div className="d-flex align-items-center gap-2">
          <ProviderBadge provider={provider} showLabel={false} />
          {recommended && (
            <span style={{ fontSize: '.76rem', color: 'var(--tx2)' }}>
              {recommended.name}
            </span>
          )}
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontWeight: 700 }} className="gt">
            {formatCurrency(estimatedCost)}
          </div>
          <div style={{ fontSize: '.68rem', color: 'var(--tx3)' }}>est. / month</div>
        </div>
      </div>
    </div>
  );
}
