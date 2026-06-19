/**
 * DockerValidationPanel — the "Docker Validation Results" panel. Renders the
 * validation the InfrastructureAgent produced for the generated Dockerfile,
 * exactly as the backend returned it: an overall status plus errors, warnings
 * and recommendations. Nothing is hidden — every finding is shown.
 *
 * Props:
 *  - validation  mapped validation block (see mapDockerPhase)
 */
const STATUS_META = {
  passed: { label: 'Passed', variant: 'success', icon: 'fa-circle-check' },
  warnings: { label: 'Passed with warnings', variant: 'warning', icon: 'fa-triangle-exclamation' },
  failed: { label: 'Failed', variant: 'danger', icon: 'fa-circle-xmark' },
  not_run: { label: 'Not validated', variant: 'pending', icon: 'fa-minus' },
};

const GROUPS = [
  { key: 'errors', label: 'Errors', icon: 'fa-circle-xmark', color: '#f87171' },
  { key: 'warnings', label: 'Warnings', icon: 'fa-triangle-exclamation', color: '#fbbf24' },
  { key: 'recommendations', label: 'Recommendations', icon: 'fa-lightbulb', color: '#60a5fa' },
];

function IssueList({ items, icon, color }) {
  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.map((it, i) => (
        <li key={i} className="d-flex align-items-start gap-2" style={{ fontSize: '.82rem' }}>
          <i className={`fa-solid ${icon}`} style={{ color, marginTop: 3, flexShrink: 0 }} />
          <div style={{ minWidth: 0 }}>
            <span>{it.message}</span>
            {it.rule && (
              <span className="tag" style={{ marginLeft: 8, fontSize: '.68rem' }}>{it.rule}</span>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function DockerValidationPanel({ validation = {} }) {
  const status = validation.status || 'not_run';
  const meta = STATUS_META[status] || STATUS_META.not_run;
  const counts = {
    errors: validation.errors || [],
    warnings: validation.warnings || [],
    recommendations: validation.recommendations || [],
  };
  const total = counts.errors.length + counts.warnings.length + counts.recommendations.length;

  return (
    <div className="surface">
      <div className="d-flex align-items-center gap-2 flex-wrap mb-1">
        <span className={`badge-pill badge-${meta.variant}`}>
          <i className={`fa-solid ${meta.icon} me-1`} />
          {meta.label}
        </span>
        <span className="tag" style={{ fontSize: '.72rem' }}>{counts.errors.length} errors</span>
        <span className="tag" style={{ fontSize: '.72rem' }}>{counts.warnings.length} warnings</span>
        <span className="tag" style={{ fontSize: '.72rem' }}>{counts.recommendations.length} recommendations</span>
      </div>

      {status === 'not_run' ? (
        <p style={{ fontSize: '.84rem', color: 'var(--tx3)', margin: '8px 0 0' }}>
          This Dockerfile has not been validated yet.
        </p>
      ) : total === 0 ? (
        <p style={{ fontSize: '.84rem', color: 'var(--tx2)', margin: '8px 0 0' }}>
          <i className="fa-solid fa-circle-check me-2" style={{ color: '#34d399' }} />
          No issues found — the generated Dockerfile passed all checks.
        </p>
      ) : (
        <div className="d-flex flex-column gap-3 mt-2">
          {GROUPS.map(({ key, label, icon, color }) =>
            counts[key].length ? (
              <div key={key}>
                <div className="section-label" style={{ marginTop: 0, marginBottom: 8 }}>
                  <i className={`fa-solid ${icon}`} style={{ color, marginRight: 8 }} />
                  {label}
                  <span className="section-label-by">{counts[key].length}</span>
                </div>
                <IssueList items={counts[key]} icon={icon} color={color} />
              </div>
            ) : null
          )}
        </div>
      )}
    </div>
  );
}
