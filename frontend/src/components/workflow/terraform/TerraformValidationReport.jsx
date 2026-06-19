/**
 * TerraformValidationReport — renders the persisted `validation_report` artifact
 * (subtype terraform_validation.json) the backend writes after a validation run.
 * Faithful to the stored payload: an overall pass/fail header (+ failure
 * classification + error), then each terraform step (init / validate) with its
 * return code and the captured terraform output. Read-only; reuses existing
 * surface / badge / mono primitives — no new viewer system.
 *
 * @param {{ report: {
 *   validationStatus: string, ok: boolean, error: ?string,
 *   failureClassification: ?string, updatedAt: ?string,
 *   steps: Array<{ step: string, ok: boolean, returnCode: ?number, output: string }>
 * } }} props
 */
export default function TerraformValidationReport({ report }) {
  if (!report) return null;
  const passed = report.ok;
  const updated = report.updatedAt ? safeDate(report.updatedAt) : null;

  return (
    <div className="surface">
      {/* ── Overall header ───────────────────────────────────────────────── */}
      <div className="d-flex align-items-center gap-3 flex-wrap">
        <span
          className="badge-pill"
          style={{
            background: passed ? 'rgba(52,211,153,.12)' : 'rgba(248,113,113,.12)',
            color: passed ? '#34d399' : '#f87171',
            fontWeight: 600,
          }}
        >
          <i className={`fa-solid ${passed ? 'fa-circle-check' : 'fa-circle-xmark'} me-2`} />
          {passed ? 'Validation passed' : 'Validation failed'}
        </span>
        {report.failureClassification && (
          <span className="tag mono" style={{ fontSize: '.72rem', color: '#fbbf24' }}>
            <i className="fa-solid fa-tag me-1" />
            {report.failureClassification}
          </span>
        )}
        {updated && (
          <span className="text-muted-3" style={{ fontSize: '.74rem' }}>
            <i className="fa-solid fa-clock me-1" />
            {updated}
          </span>
        )}
      </div>

      {report.error && !passed && (
        <div
          className="mt-2"
          style={{ fontSize: '.82rem', color: 'var(--tx2)' }}
        >
          <i className="fa-solid fa-triangle-exclamation me-2" style={{ color: '#f87171' }} />
          {report.error}
        </div>
      )}

      {/* ── Per-step results ─────────────────────────────────────────────── */}
      {report.steps.length > 0 && (
        <div className="mt-3 d-flex flex-column gap-2">
          {report.steps.map((s, i) => (
            <details key={`${s.step}-${i}`} open={!s.ok}>
              <summary
                style={{
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  fontSize: '.84rem',
                }}
              >
                <i
                  className={`fa-solid ${s.ok ? 'fa-circle-check' : 'fa-circle-xmark'}`}
                  style={{ color: s.ok ? '#34d399' : '#f87171' }}
                />
                <span className="mono" style={{ fontWeight: 600 }}>
                  terraform {s.step}
                </span>
                {s.returnCode != null && (
                  <span className="text-muted-3" style={{ fontSize: '.74rem' }}>
                    exit {s.returnCode}
                  </span>
                )}
              </summary>
              {s.output ? (
                <pre
                  className="mono mt-2"
                  style={{
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    fontSize: '.76rem',
                    background: 'var(--bg2, rgba(0,0,0,.18))',
                    border: '1px solid var(--bd)',
                    borderRadius: 6,
                    padding: '10px 12px',
                    maxHeight: 280,
                    overflow: 'auto',
                  }}
                >
                  {s.output}
                </pre>
              ) : (
                <div className="text-muted-3 mt-2" style={{ fontSize: '.78rem' }}>
                  No output captured for this step.
                </div>
              )}
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

function safeDate(iso) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
