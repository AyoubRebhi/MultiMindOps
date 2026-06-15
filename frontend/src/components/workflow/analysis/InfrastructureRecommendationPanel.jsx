import PhaseStatusCard from '@/components/workflow/PhaseStatusCard';
import { Subhead, RecoRow } from './AnalysisPanelBits';

/** Ordered recommendation groups with their section icons. */
const GROUPS = [
  { key: 'compute', label: 'Compute', icon: 'fa-microchip' },
  { key: 'storage', label: 'Storage', icon: 'fa-box-archive' },
  { key: 'networking', label: 'Networking', icon: 'fa-network-wired' },
  { key: 'observability', label: 'Observability', icon: 'fa-chart-line' },
];

/**
 * InfrastructureRecommendationPanel — infrastructure planning output and the
 * bridge toward Terraform generation. Consumes
 * WorkflowAnalysis.infrastructureRecommendations.
 *
 * @param {{ data: import('@/types/workflowAnalysis').InfrastructureRecommendations }} props
 */
export default function InfrastructureRecommendationPanel({ data }) {
  const infra = data || {};
  const aws = Array.isArray(infra.awsServices) ? infra.awsServices : [];

  return (
    <PhaseStatusCard
      icon="fa-cloud-arrow-up"
      title="Infrastructure Recommendation"
      subtitle="Recommended cloud building blocks — the bridge to Terraform generation"
      actions={<span className="badge-pill badge-warning"><i className="fa-brands fa-aws" />AWS</span>}
    >
      {!!aws.length && (
        <>
          <Subhead>Recommended AWS Services</Subhead>
          <div className="d-flex flex-column gap-2 mb-2">
            {aws.map((r) => (
              <RecoRow key={r.service} icon={r.icon || 'fa-aws'} title={r.service} detail={r.reason} />
            ))}
          </div>
        </>
      )}

      <div className="row g-3 mt-1">
        {GROUPS.map((g) => {
          const items = Array.isArray(infra[g.key]) ? infra[g.key] : [];
          if (!items.length) return null;
          return (
            <div className="col-md-6" key={g.key}>
              <Subhead>
                <i className={`fa-solid ${g.icon} me-2`} style={{ color: 'var(--pur)' }} />
                {g.label}
              </Subhead>
              <ul className="check-list">
                {items.map((r) => (
                  <li key={r.service}>
                    <i className={`fa-solid ${r.icon || 'fa-circle-check'}`} />
                    <span>
                      <strong style={{ fontWeight: 600 }}>{r.service}</strong>
                      {r.reason && (
                        <span className="text-muted-3" style={{ display: 'block', fontSize: '.76rem' }}>
                          {r.reason}
                        </span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </PhaseStatusCard>
  );
}
