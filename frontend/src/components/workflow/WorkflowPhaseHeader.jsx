import StatusBadge from '@/components/common/StatusBadge';

/**
 * WorkflowPhaseHeader — title block for a workflow phase page, shown directly
 * under the <WorkflowTimeline />. Icon + phase name + one-line description on
 * the left, an optional status badge and actions slot on the right.
 *
 * Props:
 *  - icon: Font Awesome class (e.g. "fa-clipboard-list")
 *  - brand: use fa-brands for the icon (e.g. the Docker logo)
 *  - eyebrow: small label above the title (e.g. "Phase 2 of 6")
 *  - title, subtitle
 *  - status: optional lifecycle status → <StatusBadge />
 *  - actions: optional node on the far right
 */
export default function WorkflowPhaseHeader({
  icon = 'fa-diagram-project',
  brand = false,
  eyebrow,
  title,
  subtitle,
  status,
  actions,
}) {
  return (
    <div className="wf-phase-header">
      <div className="d-flex align-items-center gap-3" style={{ minWidth: 0 }}>
        <div className="wf-phase-icon">
          <i className={`${brand ? 'fa-brands' : 'fa-solid'} ${icon}`} />
        </div>
        <div style={{ minWidth: 0 }}>
          {eyebrow && <div className="wf-phase-eyebrow">{eyebrow}</div>}
          <h1 className="wf-phase-title">{title}</h1>
          {subtitle && <p className="wf-phase-subtitle">{subtitle}</p>}
        </div>
      </div>

      <div className="d-flex align-items-center gap-2 flex-shrink-0">
        {status && <StatusBadge status={status} />}
        {actions}
      </div>
    </div>
  );
}
