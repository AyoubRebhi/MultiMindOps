import { formatDate } from '@/utils/formatters';

/**
 * PipelineResultCard — the final outcome of the CI/CD phase (Section 10).
 * Success shows the generated pipeline summary (workflow file, duration, jobs,
 * steps, security score, checksum); failure shows the failed stage, reason and
 * suggested next action.
 *
 * Props:
 *  - result: success or failed result (see mockPipelineResults)
 */
function Metric({ icon, label, value, mono = false, tone }) {
  return (
    <div className="build-metric">
      <div className="build-metric-ico">
        <i className={`fa-solid ${icon}`} style={tone ? { color: tone } : undefined} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div className="build-metric-label">{label}</div>
        <div className={`build-metric-value ${mono ? 'mono' : ''}`.trim()}>{value}</div>
      </div>
    </div>
  );
}

export default function PipelineResultCard({ result }) {
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
          <p className="phase-card-subtitle">
            {success ? (
              <span className="mono">{result.workflowFile}</span>
            ) : (
              result.failureReason
            )}
          </p>
        </div>
      </div>

      {success ? (
        <div className="build-metrics">
          <Metric icon="fa-file-code" label="Workflow File" value={result.workflowFile.split('/').pop()} mono />
          <Metric icon="fa-stopwatch" label="Execution Duration" value={result.executionDuration} />
          <Metric icon="fa-diagram-project" label="Jobs Created" value={result.jobsCreated} />
          <Metric icon="fa-list-check" label="Steps Created" value={result.stepsCreated} />
          <Metric icon="fa-shield-halved" label="Security Score" value={`${result.securityScore} · ${result.securityGrade}`} tone="#34d399" />
          <Metric icon="fa-fingerprint" label="Checksum" value={result.checksum} mono />
        </div>
      ) : (
        <div className="tf-fail-grid">
          <div className="tf-fail-block">
            <div className="tf-error-label">Failed Stage</div>
            <p className="mb-0">
              <span className="tag mono">{result.failedStage}</span>
            </p>
          </div>
          <div className="tf-fail-block">
            <div className="tf-error-label">Failure Reason</div>
            <p className="mb-0" style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>
              {result.failureReason}
            </p>
          </div>
          <div className="tf-fail-block tf-error-reco">
            <div className="tf-error-label">
              <i className="fa-solid fa-wand-magic-sparkles me-2" style={{ color: '#a78bfa' }} />
              Suggested Action
            </div>
            <p className="mb-0" style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>
              {result.suggestedAction}
            </p>
          </div>
        </div>
      )}

      {success && (
        <div className="pipeline-result-foot">
          <i className="fa-solid fa-calendar-check me-2" />
          Generated {formatDate(result.generatedAt)}
        </div>
      )}
    </div>
  );
}
