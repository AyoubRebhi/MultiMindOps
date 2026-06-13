import RealtimeLogViewer from './RealtimeLogViewer';

/**
 * WorkflowValidationPanel — runs the (mock) schema validation of the generated
 * workflow through the reusable log viewer, and on failure renders the findings
 * table (severity / line / issue / suggested fix) with Fix Manually + Revalidate.
 *
 * Props:
 *  - status: 'not_started' | 'running' | 'completed' | 'failed'
 *  - events, playKey, onRun, onComplete, canRun, preparing  (log viewer wiring)
 *  - findings: [{ id, severity, line, issue, suggestedFix, rule }]
 *  - onFixManually(): open the workflow editor in edit mode
 */
const SEV_VARIANT = { critical: 'danger', high: 'danger', medium: 'warning', low: 'info' };

export default function WorkflowValidationPanel({
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
        title="actionlint · schema validate"
        emptyHint={
          canRun
            ? 'Run validation to parse the workflow and check jobs, steps and syntax.'
            : 'Approve the generated workflow above to enable validation.'
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

          <div className="tf-findings-table wfv-findings-table">
            <div className="tf-find-row wfv-find-row tf-find-header">
              <span>Severity</span>
              <span>Line</span>
              <span>Issue</span>
              <span>Suggested Fix</span>
            </div>
            {findings.map((f) => (
              <div className="tf-find-row wfv-find-row" key={f.id}>
                <span>
                  <span className={`badge-pill badge-${SEV_VARIANT[f.severity] || 'info'}`}>
                    {f.severity}
                  </span>
                </span>
                <span className="mono">:{f.line}</span>
                <span className="tf-find-msg">
                  {f.issue}
                  {f.rule && <span className="tf-find-rule">{f.rule}</span>}
                </span>
                <span className="wfv-find-fix">
                  <i className="fa-solid fa-wand-magic-sparkles me-1" style={{ color: '#a78bfa' }} />
                  {f.suggestedFix}
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
