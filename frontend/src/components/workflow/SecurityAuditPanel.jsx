/**
 * SecurityAuditPanel — the Security Guardrails Audit (Section 7). Runs a (mock)
 * audit, then visualizes the result as security cards: a score ring, risk
 * level, per-category verdicts (dangerous commands, secrets, third-party
 * actions, permissions, suspicious URLs), warnings and critical findings.
 *
 * On a failing audit the user can Fix Workflow, Approve Anyway, or Re-run Audit.
 *
 * Props:
 *  - status: 'not_started' | 'running' | 'passed' | 'failed'
 *  - audit: result object (see mockSecurityAudit) or null
 *  - canRun, onRun()
 *  - approvedAnyway: boolean
 *  - onFix(), onApproveAnyway()
 */
const CAT_STATE = {
  pass: { variant: 'success', icon: 'fa-circle-check', label: 'Pass' },
  warn: { variant: 'warning', icon: 'fa-triangle-exclamation', label: 'Warn' },
  fail: { variant: 'danger', icon: 'fa-circle-xmark', label: 'Fail' },
};
const RISK_VARIANT = { low: 'success', medium: 'warning', high: 'danger', critical: 'danger' };

function scoreColor(score) {
  if (score >= 85) return '#34d399';
  if (score >= 60) return '#fbbf24';
  return '#f87171';
}

export default function SecurityAuditPanel({
  status = 'not_started',
  audit = null,
  canRun = true,
  onRun,
  approvedAnyway = false,
  onFix,
  onApproveAnyway,
}) {
  const running = status === 'running';
  const done = status === 'passed' || status === 'failed';
  const failed = status === 'failed';
  const runLabel = status === 'not_started' ? 'Run Security Audit' : 'Re-run Audit';

  return (
    <div>
      {/* Run bar */}
      <div className="sec-run-bar">
        <div className="sec-run-info">
          <i className="fa-solid fa-shield-halved" />
          <span>
            {canRun
              ? 'Scan the workflow for dangerous commands, exposed secrets, unverified actions, risky permissions and suspicious URLs.'
              : 'Validation must pass before the security audit can run.'}
          </span>
        </div>
        <button
          type="button"
          className="bgrd btn px-3 py-2 code-action"
          disabled={!canRun || running}
          onClick={onRun}
        >
          {running ? (
            <><i className="fa-solid fa-spinner fa-spin me-2" />Auditing…</>
          ) : (
            <><i className="fa-solid fa-shield-halved me-2" />{runLabel}</>
          )}
        </button>
      </div>

      {running && (
        <div className="compiler-busy">
          <i className="fa-solid fa-radar fa-spin" />
          <span>Running security guardrails over the workflow…</span>
        </div>
      )}

      {audit && done && (
        <div className="sec-audit">
          {/* Score + risk */}
          <div className="sec-audit-top">
            <div className="score-ring" style={{ '--pct': audit.score, '--ring': scoreColor(audit.score) }}>
              <div className="score-ring-inner">
                <span className="score-ring-num">{audit.score}</span>
                <span className="score-ring-grade">Grade {audit.grade}</span>
              </div>
            </div>
            <div className="sec-audit-summary">
              <div className="d-flex align-items-center gap-2 flex-wrap">
                <span className="reasoning-label mb-0">Security Score</span>
                <span className={`badge-pill badge-${RISK_VARIANT[String(audit.riskLevel).toLowerCase()] || 'info'}`}>
                  <i className="fa-solid fa-gauge-high" />
                  {audit.riskLevel} Risk
                </span>
                {approvedAnyway && (
                  <span className="badge-pill badge-warning">
                    <i className="fa-solid fa-circle-exclamation" />Approved with warnings
                  </span>
                )}
              </div>
              <p className="mb-0 mt-2" style={{ fontSize: '.84rem', color: 'var(--tx2)' }}>
                {failed
                  ? `${audit.criticalFindings.length} critical finding(s) and ${audit.warnings.length} warning(s) detected by the guardrails audit.`
                  : 'No critical findings — the workflow passed all security guardrails.'}
              </p>
            </div>
          </div>

          {/* Category cards */}
          <div className="sec-cat-grid">
            {audit.categories.map((c) => {
              const st = CAT_STATE[c.status] || CAT_STATE.pass;
              return (
                <div className={`sec-cat sec-cat-${c.status}`} key={c.key}>
                  <div className="sec-cat-head">
                    <span className="sec-cat-ico"><i className={`fa-solid ${c.icon}`} /></span>
                    <span className={`badge-pill badge-${st.variant}`}>
                      <i className={`fa-solid ${st.icon}`} />{st.label}
                    </span>
                  </div>
                  <div className="sec-cat-name">{c.name}</div>
                  <p className="sec-cat-detail">{c.detail}</p>
                </div>
              );
            })}
          </div>

          {/* Critical findings */}
          {audit.criticalFindings.length > 0 && (
            <>
              <div className="reasoning-label mt-3">
                <i className="fa-solid fa-skull-crossbones me-2" style={{ color: '#f87171' }} />
                Critical Findings
              </div>
              <div className="d-flex flex-column gap-2 mt-2">
                {audit.criticalFindings.map((f) => (
                  <div className="finding-row" key={f.id}>
                    <span className="finding-ico badge-danger">
                      <i className={`fa-solid ${f.icon}`} />
                    </span>
                    <div style={{ minWidth: 0 }}>
                      <div className="d-flex align-items-center gap-2 flex-wrap">
                        <span style={{ fontWeight: 600, fontSize: '.86rem' }}>{f.title}</span>
                        <span className="tag">{f.category}</span>
                        <span className="tag mono">:{f.line}</span>
                      </div>
                      <p className="mb-0" style={{ fontSize: '.8rem', color: 'var(--tx3)' }}>
                        {f.detail}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          {/* Warnings */}
          {audit.warnings.length > 0 && (
            <>
              <div className="reasoning-label mt-3">
                <i className="fa-solid fa-bell me-2" style={{ color: '#fbbf24' }} />
                Warnings
              </div>
              <ul className="check-list warn mt-1">
                {audit.warnings.map((w, i) => (
                  <li key={i}>
                    <i className="fa-solid fa-triangle-exclamation" />
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {/* Actions on failure */}
          {failed && !approvedAnyway && (
            <div className="tf-panel-actions mt-3">
              <button type="button" className="boc btn px-3 py-2 code-action" onClick={onApproveAnyway}>
                <i className="fa-solid fa-circle-exclamation me-2" />Approve Anyway
              </button>
              <button type="button" className="boc btn px-3 py-2 code-action" onClick={onFix}>
                <i className="fa-solid fa-pen-to-square me-2" />Fix Workflow
              </button>
              <button type="button" className="bgrd btn px-3 py-2 code-action" onClick={onRun}>
                <i className="fa-solid fa-rotate me-2" />Re-run Audit
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
