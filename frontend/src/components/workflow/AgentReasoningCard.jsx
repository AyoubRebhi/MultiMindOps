/**
 * AgentReasoningCard — an "AI reasoning" card visualizing the Intent Extraction
 * Agent's structured result (Section 2): the extracted intent, request type,
 * confidence score, its chain-of-thought, the detected requirements and the
 * resolved deployment target.
 *
 * Props:
 *  - data: see mockIntentExtraction (agent, model, intent, requestType,
 *    confidenceScore, reasoning[], detectedRequirements[], deploymentTarget)
 */
export default function AgentReasoningCard({ data }) {
  if (!data) return null;
  const {
    agent = 'Intent Extraction Agent',
    model,
    intent,
    requestType,
    confidenceScore = 0,
    reasoning = [],
    detectedRequirements = [],
    deploymentTarget,
  } = data;

  return (
    <div className="surface reasoning-card">
      <div className="reasoning-head">
        <span className="reasoning-ai-ico">
          <i className="fa-solid fa-brain" />
        </span>
        <div style={{ minWidth: 0 }}>
          <h3 className="card-title">{agent}</h3>
          <p className="phase-card-subtitle">
            <i className="fa-solid fa-microchip me-1" />
            {model ? `Reasoning with ${model}` : 'AI intent reasoning'}
          </p>
        </div>
        <span className="reasoning-conf">
          <span className="reasoning-conf-num">{confidenceScore}%</span>
          <span className="reasoning-conf-label">confidence</span>
        </span>
      </div>

      <div className="reasoning-intent">
        <div className="reasoning-label">Detected Intent</div>
        <p className="reasoning-intent-text">{intent}</p>
        <div className="d-flex align-items-center gap-2 flex-wrap mt-2">
          <span className="badge-pill badge-info">
            <i className="fa-solid fa-tag" />
            {requestType}
          </span>
          <div className="reasoning-conf-bar" title={`${confidenceScore}% confidence`}>
            <span style={{ width: `${confidenceScore}%` }} />
          </div>
        </div>
      </div>

      <div className="reasoning-grid">
        {/* Chain of thought */}
        <div className="reasoning-block">
          <div className="reasoning-label">
            <i className="fa-solid fa-diagram-next me-2" style={{ color: '#a78bfa' }} />
            Agent Reasoning
          </div>
          <ol className="reasoning-steps">
            {reasoning.map((r, i) => (
              <li key={i}>
                <span className="reasoning-step-n">{i + 1}</span>
                <span>{r}</span>
              </li>
            ))}
          </ol>
        </div>

        {/* Detected requirements */}
        <div className="reasoning-block">
          <div className="reasoning-label">
            <i className="fa-solid fa-list-check me-2" style={{ color: '#34d399' }} />
            Detected Requirements
          </div>
          <ul className="reasoning-reqs">
            {detectedRequirements.map((req, i) => (
              <li key={i}>
                <i className={`${req.brand ? 'fa-brands' : 'fa-solid'} ${req.icon} reasoning-req-ico`} />
                <span>{req.label}</span>
                <i className={`fa-solid ${req.met ? 'fa-circle-check' : 'fa-circle'} reasoning-req-state ${req.met ? 'ok' : ''}`} />
              </li>
            ))}
          </ul>

          {deploymentTarget && (
            <div className="reasoning-target">
              <span className="reasoning-target-ico">
                <i className={`fa-brands ${deploymentTarget.icon}`} />
              </span>
              <div style={{ minWidth: 0 }}>
                <div className="reasoning-label mb-0">Deployment Target</div>
                <div className="reasoning-target-text">
                  {deploymentTarget.provider} · {deploymentTarget.service}
                  <span className="text-muted-3"> · {deploymentTarget.region}</span>
                </div>
                <div className="reasoning-target-sub">
                  Registry: {deploymentTarget.registry}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
