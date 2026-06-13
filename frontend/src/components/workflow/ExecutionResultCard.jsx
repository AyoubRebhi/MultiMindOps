import { formatDate } from '@/utils/formatters';

/**
 * ExecutionResultCard — the outcome of the pipeline run (Section 8 of the
 * Execution Center). Success shows the run summary (duration, completed/failed
 * stages, artifacts, deployment time); failure shows the failed stage, reason
 * and recommended fix. Built on the shared build-result / build-metrics styles.
 *
 * Props:
 *  - result: see mockExecutionResult{Success,Failed}
 */
function Metric({ icon, label, value, tone }) {
  return (
    <div className="build-metric">
      <div className="build-metric-ico">
        <i className={`fa-solid ${icon}`} style={tone ? { color: tone } : undefined} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div className="build-metric-label">{label}</div>
        <div className="build-metric-value">{value}</div>
      </div>
    </div>
  );
}

export default function ExecutionResultCard({ result }) {
  if (!result) return null;
  const success = result.status === 'completed';

  return (
    <div className={`surface build-result ${success ? 'is-success' : 'is-failed'}`}>
      <div className="build-result-head">
        <span className={`build-result-ico ${success ? 'ok' : 'bad'}`}>
          <i className={`fa-solid ${success ? 'fa-circle-check' : 'fa-circle-xmark'}`} />
        </span>
        <div style={{ minWidth: 0 }}>
          <h3 className="card-title">{result.title}</h3>
          <p className="phase-card-subtitle">{result.subtitle}</p>
        </div>
      </div>

      <div className="build-metrics">
        <Metric icon="fa-stopwatch" label="Total Duration" value={result.totalDuration} />
        <Metric icon="fa-circle-check" label="Completed Stages" value={result.completedStages} tone="#34d399" />
        <Metric icon="fa-circle-xmark" label="Failed Stages" value={result.failedStages} tone={result.failedStages > 0 ? '#f87171' : undefined} />
        <Metric icon="fa-box-archive" label="Artifacts Generated" value={result.artifactsGenerated} />
        <Metric
          icon="fa-calendar-check"
          label="Deployment Time"
          value={result.deploymentTime ? formatDate(result.deploymentTime) : '—'}
        />
      </div>

      {!success && (
        <div className="tf-fail-grid mt-3">
          <div className="tf-fail-block">
            <div className="tf-error-label">Failed Stage</div>
            <p className="mb-0"><span className="tag mono">{result.failedStage}</span></p>
          </div>
          <div className="tf-fail-block">
            <div className="tf-error-label">Failure Reason</div>
            <p className="mb-0" style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>{result.failureReason}</p>
          </div>
          <div className="tf-fail-block tf-error-reco">
            <div className="tf-error-label">
              <i className="fa-solid fa-wand-magic-sparkles me-2" style={{ color: '#a78bfa' }} />
              Recommended Fix
            </div>
            <p className="mb-0" style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>{result.recommendedFix}</p>
          </div>
        </div>
      )}
    </div>
  );
}
