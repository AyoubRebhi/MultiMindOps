/**
 * BuildResultCard — the outcome of a Docker build. Renders a success summary
 * (image name, size, duration, digest, layers) or a failure summary (reason,
 * failed step, corrector recommendation).
 *
 * Props:
 *  - result: { status: 'completed' | 'failed', ... } (see dockerApi)
 */
function Metric({ icon, label, value, mono = false }) {
  return (
    <div className="build-metric">
      <div className="build-metric-ico">
        <i className={`fa-solid ${icon}`} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div className="build-metric-label">{label}</div>
        <div className={`build-metric-value ${mono ? 'mono' : ''}`.trim()}>{value}</div>
      </div>
    </div>
  );
}

export default function BuildResultCard({ result }) {
  if (!result) return null;
  const success = result.status === 'completed';

  return (
    <div className={`surface build-result ${success ? 'is-success' : 'is-failed'}`}>
      <div className="build-result-head">
        <span className={`build-result-ico ${success ? 'ok' : 'bad'}`}>
          <i className={`fa-solid ${success ? 'fa-circle-check' : 'fa-circle-xmark'}`} />
        </span>
        <div style={{ minWidth: 0 }}>
          <h3 className="card-title">
            {success ? 'Build Successful' : 'Build Failed'}
          </h3>
          {success ? (
            <p className="phase-card-subtitle mono">{result.imageName}</p>
          ) : (
            <p className="phase-card-subtitle">{result.reason}</p>
          )}
        </div>
      </div>

      {success ? (
        <div className="build-metrics">
          <Metric icon="fa-box-archive" label="Image Size" value={result.imageSize} />
          <Metric icon="fa-stopwatch" label="Build Duration" value={result.duration} />
          <Metric icon="fa-layer-group" label="Layers" value={result.layers} />
          <Metric icon="fa-fingerprint" label="Digest" value={result.imageDigest} mono />
        </div>
      ) : (
        <div className="build-fail-detail">
          {result.failedStep && (
            <div className="mb-2">
              <span className="form-label-sm d-inline">Failed step</span>{' '}
              <span className="tag mono">{result.failedStep}</span>
            </div>
          )}
          {result.recommendation && (
            <div className="build-reco">
              <i className="fa-solid fa-wand-magic-sparkles me-2" style={{ color: '#a78bfa' }} />
              <span style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>
                {result.recommendation}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
