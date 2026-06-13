import StatusBadge from '@/components/common/StatusBadge';

/**
 * PhaseStatusCard — a numbered "section" within a workflow phase page (e.g.
 * "1 · Dockerfile Generation"). Gives every step a consistent header with an
 * icon, title, optional status badge and a right-aligned actions slot, plus a
 * left status rail that reflects the step's state.
 *
 * Props:
 *  - step: optional number/string shown in the leading chip
 *  - icon: Font Awesome class (used when no `step` chip)
 *  - brand: fa-brands icon
 *  - title (required), subtitle
 *  - status: lifecycle status → colors the rail + renders a <StatusBadge />
 *  - actions: node on the right of the header
 *  - children: section body
 *  - muted: dim the whole card (e.g. a step not yet reachable)
 */
export default function PhaseStatusCard({
  step,
  icon,
  brand = false,
  title,
  subtitle,
  status,
  actions,
  children,
  muted = false,
  className = '',
}) {
  const rail = status ? `rail-${status}` : '';

  return (
    <div
      className={`surface phase-card ${rail} ${muted ? 'is-muted' : ''} ${className}`.trim()}
    >
      <div className="phase-card-head">
        <div className="d-flex align-items-center gap-3" style={{ minWidth: 0 }}>
          {step != null ? (
            <span className="phase-step-chip">{step}</span>
          ) : icon ? (
            <span className="phase-step-chip">
              <i className={`${brand ? 'fa-brands' : 'fa-solid'} ${icon}`} />
            </span>
          ) : null}
          <div style={{ minWidth: 0 }}>
            <h3 className="card-title">{title}</h3>
            {subtitle && (
              <p className="phase-card-subtitle">{subtitle}</p>
            )}
          </div>
        </div>
        <div className="d-flex align-items-center gap-2 flex-shrink-0">
          {status && <StatusBadge status={status} />}
          {actions}
        </div>
      </div>
      {children && <div className="phase-card-body">{children}</div>}
    </div>
  );
}
