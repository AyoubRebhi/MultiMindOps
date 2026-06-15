import PhaseStatusCard from '@/components/workflow/PhaseStatusCard';
import Tag from '@/components/common/Tag';
import { Subhead, CheckList } from './AnalysisPanelBits';

/** Architecture model → display chip metadata. */
const MODEL_META = {
  MONOLITH: { label: 'Monolith', icon: 'fa-cube' },
  MICROSERVICES: { label: 'Microservices', icon: 'fa-diagram-project' },
  SERVERLESS: { label: 'Serverless', icon: 'fa-bolt' },
  HYBRID: { label: 'Hybrid', icon: 'fa-shapes' },
};

/**
 * ArchitectureIntelligencePanel — AI architecture conclusions. Consumes
 * WorkflowAnalysis.architecture.
 *
 * @param {{ data: import('@/types/workflowAnalysis').Architecture }} props
 */
export default function ArchitectureIntelligencePanel({ data }) {
  const a = data || {};
  const model = MODEL_META[a.model] || { label: a.model || 'Unknown', icon: 'fa-sitemap' };

  return (
    <PhaseStatusCard
      icon="fa-sitemap"
      title="Architecture Intelligence"
      subtitle="AI conclusions about how the system is structured and should be deployed"
      actions={
        a.confidence != null ? (
          <span className="badge-pill badge-info">
            <i className="fa-solid fa-wand-magic-sparkles" />
            {a.confidence}% match
          </span>
        ) : null
      }
    >
      <div className="d-flex flex-wrap align-items-center gap-2 mb-2">
        <span className="badge-pill badge-running">
          <i className={`fa-solid ${model.icon}`} />
          {model.label}
        </span>
        {a.architectureType && <Tag icon="fa-layer-group">{a.architectureType}</Tag>}
      </div>

      <div className="row g-3">
        <div className="col-md-6">
          <Subhead>Suggested Architecture Pattern</Subhead>
          <p style={{ fontSize: '.83rem', color: 'var(--tx2)', margin: 0 }}>
            {a.suggestedPattern || '—'}
          </p>

          <Subhead className="mt-3">Deployment Strategy</Subhead>
          <p style={{ fontSize: '.83rem', color: 'var(--tx2)', margin: 0 }}>
            {a.deploymentStrategy || '—'}
          </p>
        </div>

        <div className="col-md-6">
          <Subhead>Scaling Assumptions</Subhead>
          <CheckList items={a.scalingAssumptions} icon="fa-up-right-and-down-left-from-center" empty="No scaling assumptions" />
        </div>
      </div>

      <Subhead className="mt-3">Architectural Observations</Subhead>
      <CheckList items={a.observations} icon="fa-magnifying-glass" empty="No observations" />
    </PhaseStatusCard>
  );
}
