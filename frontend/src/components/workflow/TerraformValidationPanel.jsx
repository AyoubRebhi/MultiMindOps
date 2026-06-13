import RealtimeLogViewer from './RealtimeLogViewer';

/**
 * TerraformValidationPanel — runs the (mock) `fmt → init → validate` sequence
 * through the reusable log viewer, and on failure renders the validation
 * findings (severity / file / line / message) with Fix Manually + Revalidate.
 *
 * Props:
 *  - status: 'not_started' | 'running' | 'completed' | 'failed'
 *  - events, playKey, onRun, onComplete, canRun, preparing  (log viewer wiring)
 *  - findings: [{ id, severity, file, line, message, rule }]
 *  - onFixManually(): open the manual correction workspace
 */
const SEV_VARIANT = { high: 'danger', critical: 'danger', medium: 'warning', low: 'info' };

export default function TerraformValidationPanel({
  status = 'not_started',
  events = [],
  playKey = 0,
  onRun,
  onComplete,
  canRun = true,
  preparing = false,
  findings = [],
  onFixManually,
}) {
  const startLabel =
    status === 'failed' ? 'Revalidate' : status === 'completed' ? 'Re-run validation' : 'Run Validation';

  return (
    <div>
      <RealtimeLogViewer
        events={events}
        playKey={playKey}
        canStart={canRun}
        preparing={preparing}
        onStart={onRun}
        onComplete={onComplete}
        startLabel={startLabel}
        title="terraform validate"
        emptyHint={
          canRun
            ? 'Run validation to format, initialize and validate the configuration.'
            : 'Approve the Terraform plan above to enable validation.'
        }
      />

      {status === 'failed' && findings.length > 0 && (
        <div className="tf-findings">
          <div className="tf-findings-head">
            <span>
              <i className="fa-solid fa-triangle-exclamation me-2" style={{ color: '#f87171' }} />
              Validation Findings
            </span>
            <span className="text-muted-3">{findings.length} problem(s)</span>
          </div>

          <div className="tf-findings-table">
            <div className="tf-find-row tf-find-header">
              <span>Severity</span>
              <span>File</span>
              <span>Line</span>
              <span>Message</span>
            </div>
            {findings.map((f) => (
              <div className="tf-find-row" key={f.id}>
                <span>
                  <span className={`badge-pill badge-${SEV_VARIANT[f.severity] || 'info'}`}>
                    {f.severity}
                  </span>
                </span>
                <span className="mono tf-find-file">{f.file}</span>
                <span className="mono">{f.line}</span>
                <span className="tf-find-msg">
                  {f.message}
                  {f.rule && <span className="tf-find-rule">{f.rule}</span>}
                </span>
              </div>
            ))}
          </div>

          <div className="tf-panel-actions">
            <button type="button" className="boc btn px-3 py-2 code-action" onClick={onFixManually}>
              <i className="fa-solid fa-pen-to-square me-2" />Fix Manually
            </button>
            <button type="button" className="bgrd btn px-3 py-2 code-action" onClick={onRun}>
              <i className="fa-solid fa-rotate me-2" />Revalidate
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
