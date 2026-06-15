/* ============================================================================
   ProjectAnalysisStatus — visualizes the project bootstrap (analysis) state.

   Maps the backend `bootstrap_status` state machine
   (pending → analyzing → context_building → ready | failed) onto the four
   user-facing states the spec calls for: Pending, Running, Completed, Failed.

   Two render modes:
     - badge  (compact pill, used on cards / headers)
     - card   (full panel with description + optional retry, used on detail)
   ========================================================================== */

const STATE_META = {
  pending: {
    phase: 'Pending',
    label: 'Queued for analysis',
    description: 'The repository is queued. Analysis will start momentarily.',
    variant: 'pending',
    icon: 'fa-clock',
    spin: false,
  },
  analyzing: {
    phase: 'Running',
    label: 'Analyzing repository',
    description: 'The Code Base Analysis Agent is cloning and inspecting the repository.',
    variant: 'running',
    icon: 'fa-spinner',
    spin: true,
  },
  context_building: {
    phase: 'Running',
    label: 'Building project context',
    description: 'Detected stack and security findings are being assembled.',
    variant: 'running',
    icon: 'fa-spinner',
    spin: true,
  },
  ready: {
    phase: 'Completed',
    label: 'Analysis complete',
    description: 'Code analysis and security scan finished. Results are below.',
    variant: 'success',
    icon: 'fa-circle-check',
    spin: false,
  },
  failed: {
    phase: 'Failed',
    label: 'Analysis failed',
    description: 'The analysis could not complete. Review the error and retry.',
    variant: 'danger',
    icon: 'fa-circle-xmark',
    spin: false,
  },
};

function metaFor(status) {
  return STATE_META[status] || STATE_META.pending;
}

export function ProjectAnalysisStatusBadge({ status }) {
  const meta = metaFor(status);
  return (
    <span className={`badge-pill badge-${meta.variant}`}>
      <i className={`fa-solid ${meta.icon} ${meta.spin ? 'fa-spin' : ''}`.trim()} />
      {meta.phase}
    </span>
  );
}

export default function ProjectAnalysisStatus({
  status,
  error,
  onRetry,
  retrying = false,
  className = '',
}) {
  const meta = metaFor(status);
  const isFailed = status === 'failed';

  return (
    <div
      className={`surface d-flex align-items-start gap-3 ${className}`.trim()}
      style={{ borderLeft: `3px solid var(--${meta.variant === 'pending' ? 'tx3' : meta.variant}, #8b5cf6)` }}
    >
      <div
        className={`icon-tile badge-${meta.variant}`}
        style={{ flexShrink: 0 }}
        aria-hidden
      >
        <i className={`fa-solid ${meta.icon} ${meta.spin ? 'fa-spin' : ''}`.trim()} />
      </div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="d-flex align-items-center gap-2 flex-wrap">
          <span style={{ fontWeight: 600 }}>{meta.label}</span>
          <span className={`badge-pill badge-${meta.variant}`} style={{ fontSize: '.66rem' }}>
            {meta.phase}
          </span>
        </div>
        <p className="mb-0 mt-1" style={{ fontSize: '.82rem', color: 'var(--tx3)' }}>
          {meta.description}
        </p>
        {isFailed && error && (
          <pre
            className="mono mt-2 mb-0"
            style={{
              fontSize: '.72rem',
              color: '#f87171',
              background: 'rgba(248,113,113,.08)',
              padding: '8px 10px',
              borderRadius: 8,
              whiteSpace: 'pre-wrap',
              maxHeight: 120,
              overflow: 'auto',
            }}
          >
            {String(error).split('\n').slice(0, 4).join('\n')}
          </pre>
        )}
        {isFailed && onRetry && (
          <button
            type="button"
            className="boc btn px-3 py-2 mt-2"
            style={{ fontSize: '.8rem' }}
            onClick={onRetry}
            disabled={retrying}
          >
            {retrying ? (
              <>
                <span className="spinner me-2" style={{ width: 13, height: 13, borderWidth: 2 }} />
                Retrying…
              </>
            ) : (
              <>
                <i className="fa-solid fa-rotate-right me-2" />
                Retry analysis
              </>
            )}
          </button>
        )}
      </div>
    </div>
  );
}
