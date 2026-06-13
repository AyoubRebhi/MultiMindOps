import TerraformResourceSummary from './TerraformResourceSummary';
import { formatDate } from '@/utils/formatters';

/**
 * TerraformDeploymentResult — the final outcome of the Terraform phase. Success
 * shows the provisioned infrastructure summary (✓) plus run metadata; failure
 * shows the reason, last error and suggested next action.
 *
 * Props:
 *  - result: success or failed result object (see mockTerraformResults)
 *  - resources: grouped resources (for the success infra summary)
 */
function Meta({ icon, label, value }) {
  return (
    <div className="build-metric">
      <div className="build-metric-ico">
        <i className={`fa-solid ${icon}`} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div className="build-metric-label">{label}</div>
        <div className="build-metric-value">{value}</div>
      </div>
    </div>
  );
}

export default function TerraformDeploymentResult({ result, resources = [] }) {
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
            {success
              ? `${result.resourcesCreated} resources provisioned in ${result.environment} (${result.region})`
              : result.failureReason}
          </p>
        </div>
      </div>

      {success ? (
        <>
          <div className="tf-result-section-label">Infrastructure Summary</div>
          <TerraformResourceSummary resources={resources} checked />

          <div className="tf-result-section-label mt-3">Additional Information</div>
          <div className="build-metrics">
            <Meta icon="fa-stopwatch" label="Execution Duration" value={result.duration} />
            <Meta icon="fa-cubes" label="Resources Created" value={result.resourcesCreated} />
            <Meta icon="fa-calendar-check" label="Generated At" value={formatDate(result.generatedAt)} />
            <Meta icon="fa-layer-group" label="Environment" value={result.environment} />
          </div>
        </>
      ) : (
        <div className="tf-fail-grid">
          <div className="tf-fail-block">
            <div className="tf-error-label">Failure Reason</div>
            <p className="mb-0" style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>
              {result.failureReason}
            </p>
          </div>
          <div className="tf-fail-block">
            <div className="tf-error-label">Last Error</div>
            <p className="mb-0 mono" style={{ fontSize: '.8rem', color: '#fca5a5' }}>
              {result.lastError}
            </p>
          </div>
          <div className="tf-fail-block tf-error-reco">
            <div className="tf-error-label">
              <i className="fa-solid fa-wand-magic-sparkles me-2" style={{ color: '#a78bfa' }} />
              Suggested Next Action
            </div>
            <p className="mb-0" style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>
              {result.suggestedAction}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
