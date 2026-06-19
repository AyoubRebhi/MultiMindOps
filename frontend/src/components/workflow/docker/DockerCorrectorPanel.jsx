/**
 * DockerCorrectorPanel — renders the Docker Corrector's latest analysis for a
 * failed build, straight from the backend (CorrectorResult). It explains WHAT
 * the corrector found and WHY a change is needed: the root cause, the failure
 * type + confidence, the actionable fixes, and the exact file-level patches.
 *
 * Props:
 *  - corrector  mapped corrector block (see mapDockerPhase); .analysis is the
 *               raw CorrectorResult dict (snake_case, read as-is).
 */
const SEVERITY_VARIANT = {
  critical: 'danger',
  high: 'danger',
  medium: 'warning',
  low: 'info',
  info: 'info',
};

function sevVariant(s) {
  return SEVERITY_VARIANT[String(s || '').toLowerCase()] || 'info';
}

function titleize(s) {
  return String(s || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function Fix({ fix }) {
  return (
    <div className="surface" style={{ padding: '12px 14px' }}>
      <div className="d-flex align-items-center gap-2 flex-wrap">
        <i className="fa-solid fa-screwdriver-wrench" style={{ color: 'var(--tx3)' }} />
        <span style={{ fontWeight: 600, fontSize: '.85rem' }}>{fix.title || 'Remediation'}</span>
        {fix.severity && (
          <span className={`badge-pill badge-${sevVariant(fix.severity)}`} style={{ fontSize: '.7rem' }}>
            {titleize(fix.severity)}
          </span>
        )}
        {fix.applies_to && (
          <span className="tag" style={{ fontSize: '.68rem' }}>{fix.applies_to}</span>
        )}
      </div>
      {fix.explanation && (
        <p style={{ fontSize: '.82rem', color: 'var(--tx2)', margin: '8px 0 0' }}>{fix.explanation}</p>
      )}
    </div>
  );
}

function Patch({ patch }) {
  return (
    <div className="surface" style={{ padding: 0, overflow: 'hidden' }}>
      <div className="d-flex align-items-center gap-2 flex-wrap" style={{ padding: '8px 12px', borderBottom: '1px solid var(--bd)' }}>
        <span className="badge-pill badge-info" style={{ fontSize: '.68rem' }}>{titleize(patch.operation)}</span>
        <span className="tag" style={{ fontSize: '.7rem' }}>{patch.file || 'Dockerfile'}</span>
        {patch.section_id && <span className="tag" style={{ fontSize: '.68rem' }}>{patch.section_id}</span>}
      </div>
      {patch.reason && (
        <p style={{ fontSize: '.8rem', color: 'var(--tx2)', margin: 0, padding: '8px 12px 0' }}>
          <i className="fa-solid fa-circle-info me-2" style={{ color: 'var(--tx3)' }} />
          {patch.reason}
        </p>
      )}
      <div style={{ padding: '8px 12px 12px' }}>
        {patch.target && (
          <pre style={{ margin: '4px 0', padding: '6px 10px', fontSize: '.75rem', background: 'rgba(248,113,113,.12)', borderRadius: 6, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            <span style={{ color: '#f87171' }}>− </span>{patch.target}
          </pre>
        )}
        {patch.replacement && (
          <pre style={{ margin: '4px 0', padding: '6px 10px', fontSize: '.75rem', background: 'rgba(52,211,153,.12)', borderRadius: 6, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            <span style={{ color: '#34d399' }}>+ </span>{patch.replacement}
          </pre>
        )}
      </div>
    </div>
  );
}

export default function DockerCorrectorPanel({ corrector = {} }) {
  const a = corrector.analysis || {};
  const fixes = Array.isArray(a.fixes) ? a.fixes : [];
  const patches = Array.isArray(a.structured_patches) ? a.structured_patches : [];
  const confidence = typeof a.confidence === 'number' ? Math.round(a.confidence * 100) : null;
  const guidance = a.regeneration_guidance || null;
  const avoid = guidance && Array.isArray(guidance.avoid_patterns) ? guidance.avoid_patterns : [];

  return (
    <div className="d-flex flex-column gap-3">
      {/* Diagnosis header */}
      <div className="surface" style={{ borderLeft: '3px solid #f59e0b' }}>
        <div className="d-flex align-items-center gap-2 flex-wrap mb-2">
          <i className="fa-solid fa-wand-magic-sparkles" style={{ color: '#f59e0b' }} />
          <span style={{ fontWeight: 600 }}>Corrector diagnosis</span>
          {a.error_type && (
            <span className="badge-pill badge-warning" style={{ fontSize: '.72rem' }}>{titleize(a.error_type)}</span>
          )}
          {confidence != null && (
            <span className="tag" style={{ fontSize: '.72rem' }}>
              <i className="fa-solid fa-gauge-high me-1" />{confidence}% confidence
            </span>
          )}
          {corrector.status && (
            <span className="tag" style={{ fontSize: '.72rem' }}>{titleize(corrector.status)}</span>
          )}
          <span className="tag ms-auto" style={{ fontSize: '.72rem' }}>
            retry {corrector.retryCount}/{corrector.maxRetries}
          </span>
        </div>
        <div style={{ fontSize: '.72rem', color: 'var(--tx3)', textTransform: 'uppercase', letterSpacing: '.04em' }}>
          Root cause
        </div>
        <p style={{ fontSize: '.88rem', margin: '4px 0 0', color: 'var(--tx1, var(--tx2))' }}>
          {a.root_cause || 'No root cause recorded.'}
        </p>
        {(a.failed_step || a.failed_line) && (
          <div style={{ fontSize: '.78rem', color: 'var(--tx3)', marginTop: 6 }}>
            {a.failed_step && <>Failed step: <code>{a.failed_step}</code></>}
            {a.failed_line ? <> · line {a.failed_line}</> : null}
          </div>
        )}
      </div>

      {/* Fixes */}
      {fixes.length > 0 && (
        <div>
          <div className="section-label" style={{ marginTop: 0 }}>
            <i className="fa-solid fa-list-check" style={{ marginRight: 8 }} />
            Recommended fixes
            <span className="section-label-by">{fixes.length}</span>
          </div>
          <div className="d-flex flex-column gap-2">
            {fixes.map((f, i) => <Fix key={i} fix={f} />)}
          </div>
        </div>
      )}

      {/* Structured patches — the precise "what changed" */}
      {patches.length > 0 && (
        <div>
          <div className="section-label" style={{ marginTop: 0 }}>
            <i className="fa-solid fa-code-commit" style={{ marginRight: 8 }} />
            Proposed patches
            <span className="section-label-by">{patches.length}</span>
          </div>
          <div className="d-flex flex-column gap-2">
            {patches.map((p, i) => <Patch key={i} patch={p} />)}
          </div>
        </div>
      )}

      {/* Regeneration guidance */}
      {avoid.length > 0 && (
        <div className="surface">
          <div className="section-label" style={{ marginTop: 0, marginBottom: 8 }}>
            <i className="fa-solid fa-ban" style={{ marginRight: 8 }} />
            Anti-patterns to avoid
          </div>
          <div className="d-flex flex-wrap gap-2">
            {avoid.map((p, i) => (
              <span className="tag" key={i} style={{ fontSize: '.74rem' }}>{p}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
