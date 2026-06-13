import StatusBadge from '@/components/common/StatusBadge';

/**
 * DockerCorrectionPanel — the Docker Corrector Agent surface, shown only when a
 * build has failed. Presents the error summary, the categorized issues, an
 * AI-suggested fix, and a side-by-side comparison of the original vs corrected
 * Dockerfile. Actions: Approve Fix · Modify Fix · Reject Fix.
 *
 * Props:
 *  - correction: see mockDockerCorrection shape
 *  - onApprove(), onModify(), onReject()
 *  - decision: 'approved' | 'rejected' | null
 */

const SEV_VARIANT = { high: 'danger', medium: 'warning', low: 'info' };

/** Set of trimmed lines, for a cheap line-membership diff highlight. */
function lineSet(text) {
  return new Set(
    text.replace(/\n$/, '').split('\n').map((l) => l.trim()).filter(Boolean)
  );
}

function DiffColumn({ title, text, otherSet, mark }) {
  const lines = text.replace(/\n$/, '').split('\n');
  return (
    <div className="diff-col">
      <div className="diff-col-head">
        <i className={`fa-solid ${mark === 'del' ? 'fa-file-circle-xmark' : 'fa-file-circle-check'} me-2`} />
        {title}
      </div>
      <pre className="diff-pre mono">
        {lines.map((l, i) => {
          const t = l.trim();
          const changed = t && !otherSet.has(t);
          return (
            <div key={i} className={`diff-line ${changed ? `is-${mark}` : ''}`.trim()}>
              <span className="diff-sign">
                {changed ? (mark === 'del' ? '-' : '+') : ' '}
              </span>
              <span>{l || ' '}</span>
            </div>
          );
        })}
      </pre>
    </div>
  );
}

export default function DockerCorrectionPanel({
  correction,
  onApprove,
  onModify,
  onReject,
  decision = null,
}) {
  if (!correction) return null;
  const {
    errorSummary,
    issues = [],
    suggestedFix,
    originalDockerfile = '',
    correctedDockerfile = '',
    confidence,
    diagnosedBy = 'Docker Corrector Agent',
  } = correction;

  const origSet = lineSet(originalDockerfile);
  const corrSet = lineSet(correctedDockerfile);

  return (
    <div className="surface corrector-panel">
      {/* Header */}
      <div className="phase-card-head">
        <div className="d-flex align-items-center gap-3" style={{ minWidth: 0 }}>
          <span className="corrector-badge">
            <i className="fa-solid fa-wand-magic-sparkles" />
          </span>
          <div style={{ minWidth: 0 }}>
            <h3 className="card-title">Docker Corrector Agent</h3>
            <p className="phase-card-subtitle">
              {diagnosedBy}
              {confidence != null && (
                <span className="ms-2 text-muted-3">· {confidence}% confidence</span>
              )}
            </p>
          </div>
        </div>
        {decision === 'approved' && <StatusBadge status="approved" />}
        {decision === 'rejected' && <StatusBadge status="rejected" />}
      </div>

      {/* Error summary */}
      <div className="corrector-error">
        <div className="d-flex align-items-start gap-2">
          <i className="fa-solid fa-circle-exclamation" style={{ color: '#f87171', marginTop: 2 }} />
          <div>
            <div style={{ fontWeight: 600 }}>{errorSummary?.title}</div>
            <p className="mb-0" style={{ fontSize: '.83rem', color: 'var(--tx2)' }}>
              {errorSummary?.reason}
            </p>
            <div className="d-flex flex-wrap gap-2 mt-2">
              {errorSummary?.failedStep && (
                <span className="tag mono">
                  <i className="fa-solid fa-xmark" style={{ color: '#f87171' }} />
                  {errorSummary.failedStep}
                </span>
              )}
              {errorSummary?.exitCode != null && (
                <span className="tag mono">exit {errorSummary.exitCode}</span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Categorized issues */}
      {issues.length > 0 && (
        <div className="corrector-issues">
          {issues.map((it, i) => (
            <div className="corrector-issue" key={i}>
              <span className={`issue-ico badge-${SEV_VARIANT[it.severity] || 'info'}`}>
                <i className={`fa-solid ${it.icon || 'fa-triangle-exclamation'}`} />
              </span>
              <div style={{ minWidth: 0 }}>
                <div className="d-flex align-items-center gap-2 flex-wrap">
                  <span style={{ fontWeight: 600, fontSize: '.86rem' }}>{it.type}</span>
                  <span className={`badge-pill badge-${SEV_VARIANT[it.severity] || 'info'}`}>
                    {it.severity}
                  </span>
                </div>
                <p className="mb-0" style={{ fontSize: '.8rem', color: 'var(--tx3)' }}>
                  {it.detail}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* AI suggested fix */}
      {suggestedFix && (
        <div className="corrector-suggestion">
          <div className="corrector-suggestion-label">
            <i className="fa-solid fa-lightbulb me-2" />AI Suggested Fix
          </div>
          <p className="mb-0" style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>
            {suggestedFix}
          </p>
        </div>
      )}

      {/* Side-by-side comparison */}
      <div className="diff-cols">
        <DiffColumn title="Original Dockerfile" text={originalDockerfile} otherSet={corrSet} mark="del" />
        <DiffColumn title="Corrected Dockerfile" text={correctedDockerfile} otherSet={origSet} mark="add" />
      </div>

      {/* Actions */}
      <div className="corrector-actions">
        <button
          type="button"
          className="boc btn px-3 py-2 code-action code-action-danger"
          onClick={() => onReject?.()}
        >
          <i className="fa-solid fa-xmark me-2" />Reject Fix
        </button>
        <button
          type="button"
          className="boc btn px-3 py-2 code-action"
          onClick={() => onModify?.()}
        >
          <i className="fa-solid fa-pen me-2" />Modify Fix
        </button>
        <button
          type="button"
          className="bgrd btn px-3 py-2 code-action"
          disabled={decision === 'approved'}
          onClick={() => onApprove?.()}
        >
          <i className="fa-solid fa-check me-2" />
          {decision === 'approved' ? 'Fix Applied' : 'Approve Fix'}
        </button>
      </div>
    </div>
  );
}
