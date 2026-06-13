/**
 * TerraformErrorPanel — surfaces a failed `terraform apply` with the error
 * code, description and recommended action. Actions: Modify Terraform · Retry
 * Execution. Shown by the page only when execution fails.
 *
 * Props:
 *  - error: { code, title, description, recommendation, file, line, phase }
 *  - onModify(), onRetry()
 */
export default function TerraformErrorPanel({ error, onModify, onRetry }) {
  if (!error) return null;

  return (
    <div className="surface tf-error">
      <div className="tf-error-head">
        <span className="tf-error-ico">
          <i className="fa-solid fa-circle-exclamation" />
        </span>
        <div style={{ minWidth: 0 }}>
          <h3 className="card-title">{error.title || 'Execution failed'}</h3>
          <p className="phase-card-subtitle">
            Execution Error Panel{error.phase ? ` · terraform ${error.phase}` : ''}
          </p>
        </div>
        <span className="tf-error-code mono">{error.code}</span>
      </div>

      <div className="tf-error-grid">
        <div className="tf-error-block">
          <div className="tf-error-label">Error Description</div>
          <p className="mb-0" style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>
            {error.description}
          </p>
          {error.file && (
            <span className="tag mono mt-2">
              <i className="fa-solid fa-file-code" style={{ color: '#f87171' }} />
              {error.file}:{error.line}
            </span>
          )}
        </div>
        <div className="tf-error-block tf-error-reco">
          <div className="tf-error-label">
            <i className="fa-solid fa-lightbulb me-2" style={{ color: '#a78bfa' }} />
            Recommended Action
          </div>
          <p className="mb-0" style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>
            {error.recommendation}
          </p>
        </div>
      </div>

      <div className="tf-panel-actions">
        <button type="button" className="boc btn px-3 py-2 code-action" onClick={onModify}>
          <i className="fa-solid fa-pen-to-square me-2" />Modify Terraform
        </button>
        <button type="button" className="bgrd btn px-3 py-2 code-action" onClick={onRetry}>
          <i className="fa-solid fa-rotate me-2" />Retry Execution
        </button>
      </div>
    </div>
  );
}
