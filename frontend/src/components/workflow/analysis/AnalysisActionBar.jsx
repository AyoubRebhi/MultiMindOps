/**
 * AnalysisActionBar — Section B. Primary operational controls for the workflow
 * run, surfaced directly (never hidden behind a menu).
 *
 * @param {{
 *   status: import('@/types/workflowAnalysis').WorkflowAnalysisStatus,
 *   busy?: boolean,
 *   onStart: () => void,
 *   onRerun: () => void,
 *   onViewLogs: () => void,
 *   logsOpen?: boolean,
 * }} props
 */
export default function AnalysisActionBar({
  status,
  busy = false,
  onStart,
  onRerun,
  onViewLogs,
  logsOpen = false,
}) {
  const running = status === 'RUNNING';

  return (
    <div className="surface d-flex flex-wrap align-items-center gap-2 mb-3" style={{ padding: '14px 16px' }}>
      <div className="d-flex align-items-center gap-2" style={{ marginRight: 'auto' }}>
        <i className="fa-solid fa-bolt" style={{ color: 'var(--pur)' }} />
        <span style={{ fontWeight: 600, fontSize: '.9rem' }}>Workflow Controls</span>
      </div>

      <button
        type="button"
        className="bgrd btn px-3 py-2"
        style={{ fontSize: '.85rem' }}
        onClick={onStart}
        disabled={busy || running}
      >
        <i className={`fa-solid ${running ? 'fa-spinner fa-spin' : 'fa-play'} me-2`} />
        {running ? 'Workflow Running…' : 'Start Workflow'}
      </button>

      <button
        type="button"
        className="boc btn px-3 py-2"
        style={{ fontSize: '.85rem' }}
        onClick={onRerun}
        disabled={busy}
      >
        <i className={`fa-solid ${busy ? 'fa-spinner fa-spin' : 'fa-rotate-right'} me-2`} />
        Rerun Analysis
      </button>

      <button
        type="button"
        className={`boc btn px-3 py-2 ${logsOpen ? 'active' : ''}`.trim()}
        style={{ fontSize: '.85rem' }}
        onClick={onViewLogs}
        aria-pressed={logsOpen}
      >
        <i className="fa-solid fa-terminal me-2" />
        {logsOpen ? 'Hide Raw Logs' : 'View Raw Logs'}
      </button>
    </div>
  );
}
