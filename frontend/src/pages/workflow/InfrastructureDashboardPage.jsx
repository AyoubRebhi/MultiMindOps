import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import PhaseStatusCard from '@/components/workflow/PhaseStatusCard';
import DeploymentOverviewCard from '@/components/workflow/DeploymentOverviewCard';
import ResourceInventoryTable from '@/components/workflow/ResourceInventoryTable';
import InfrastructureTopology from '@/components/workflow/InfrastructureTopology';
import DeploymentMetricsCard from '@/components/workflow/DeploymentMetricsCard';
import WorkflowHistoryPanel from '@/components/workflow/WorkflowHistoryPanel';
import ArtifactExplorer from '@/components/workflow/ArtifactExplorer';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { deploymentApi } from '@/services/api/deploymentApi';
import { infrastructureApi } from '@/services/api/infrastructureApi';
import { historyApi } from '@/services/api/historyApi';
import { artifactApi } from '@/services/api/artifactApi';
import { formatDate } from '@/utils/formatters';

/**
 * InfrastructureDashboardPage — workflow Phase 7: the final outcome of the
 * deployment. Instead of a plain "Success" screen it shows what was created,
 * where, and the full resource inventory (all mock, no backend):
 *   1. Deployment Overview     → success banner + overview fields
 *   2. Infrastructure Summary  → resource category roll-up
 *   3. Resource Inventory      → searchable / sortable resource table
 *   4. Deployment Architecture → cards-and-connectors topology
 *   5. Deployment Metrics      → metric cards
 *   6. Workflow History        → previous executions
 *   7. Deployment Artifacts    → view / download artifacts
 *   8. Next Actions            → suggested follow-ups
 *
 * Route: /workflows/infrastructure-dashboard.
 */
export default function InfrastructureDashboardPage() {
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [overview, setOverview] = useState(null);
  const [summary, setSummary] = useState([]);
  const [inventory, setInventory] = useState([]);
  const [topology, setTopology] = useState(null);
  const [metrics, setMetrics] = useState([]);
  const [history, setHistory] = useState([]);
  const [artifacts, setArtifacts] = useState([]);

  useEffect(() => {
    let active = true;
    Promise.all([
      deploymentApi.getOverview(),
      infrastructureApi.getSummary(),
      infrastructureApi.getInventory(),
      infrastructureApi.getTopology(),
      infrastructureApi.getMetrics(),
      historyApi.listExecutions(),
      artifactApi.listPipelineArtifacts(),
    ]).then(([ov, sum, inv, topo, met, hist, arts]) => {
      if (!active) return;
      setOverview(ov);
      setSummary(sum);
      setInventory(inv);
      setTopology(topo);
      setMetrics(met);
      setHistory(hist);
      setArtifacts(arts);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  const downloadReport = () => {
    if (!overview) return;
    const lines = [
      'DEPLOYMENT REPORT',
      '═════════════════',
      `Status:       ${overview.bannerTitle}`,
      `Environment:  ${overview.environment}`,
      `Region:       ${overview.region} (${overview.regionLabel})`,
      `Provider:     ${overview.provider}`,
      `Workspace:    ${overview.workspace}`,
      `Deployed:     ${formatDate(overview.deploymentDate)}`,
      `Duration:     ${overview.deploymentDuration}`,
      `Endpoint:     ${overview.endpoint}`,
      '',
      'INFRASTRUCTURE SUMMARY',
      '──────────────────────',
      ...summary.map((c) => `${c.title}: ${c.items.map((i) => i.label).join(', ')}`),
      '',
      'METRICS',
      '───────',
      ...metrics.map((m) => `${m.label}: ${m.value}`),
      '',
      `Resources: ${inventory.length} total`,
    ];
    const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'deployment-report.txt';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  if (loading || !overview) {
    return (
      <ContentContainer>
        <LoadingSpinner center label="Loading the deployed infrastructure…" />
      </ContentContainer>
    );
  }

  return (
    <ContentContainer>
      <WorkflowTimeline
        current="infrastructure"
        statuses={{
          analysis: 'completed',
          planning: 'completed',
          docker: 'completed',
          terraform: 'completed',
          cicd: 'completed',
          execution: 'completed',
          infrastructure: 'completed',
        }}
      />

      <WorkflowPhaseHeader
        icon="fa-server"
        eyebrow="Phase 7 of 7"
        title="Infrastructure Dashboard"
        subtitle="The deployment is live. Here's everything that was created and where it runs."
        status="completed"
      />

      {/* ============ SECTION 1 — Deployment Overview ============ */}
      <div className="section-label">
        <span className="section-label-chip">1</span>
        Deployment Overview
        <span className="section-label-by">Production · {overview.region}</span>
      </div>
      <div className="mb-2">
        <DeploymentOverviewCard overview={overview} />
      </div>

      {/* ============ SECTION 2 — Infrastructure Summary ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">2</span>
        Infrastructure Summary
        <span className="section-label-by">{inventory.length} resources provisioned</span>
      </div>
      <div className="row g-3 mb-2">
        {summary.map((cat) => (
          <div className="col-md-6 col-xl-3" key={cat.key}>
            <PhaseStatusCard icon={cat.icon} title={cat.title}>
              <div className="d-flex flex-column gap-2">
                {cat.items.map((it) => (
                  <span className="ctx-check ok" key={it.label}>
                    <i className="fa-solid fa-circle-check" />
                    {it.label}
                  </span>
                ))}
              </div>
            </PhaseStatusCard>
          </div>
        ))}
      </div>

      {/* ============ SECTION 3 — Resource Inventory ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">3</span>
        Resource Inventory
        <span className="section-label-by">search · filter · sort</span>
      </div>
      <PhaseStatusCard
        icon="fa-list-ul"
        title="Provisioned Resources"
        subtitle="Every resource created by this deployment."
        status="completed"
        className="mb-2"
      >
        <ResourceInventoryTable resources={inventory} />
      </PhaseStatusCard>

      {/* ============ SECTION 4 — Deployment Architecture ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">4</span>
        Deployment Architecture
        <span className="section-label-by">request flow</span>
      </div>
      <PhaseStatusCard
        icon="fa-sitemap"
        title="Architecture Topology"
        subtitle="How traffic flows through the deployed infrastructure."
        status="completed"
        className="mb-2"
      >
        <InfrastructureTopology data={topology} />
      </PhaseStatusCard>

      {/* ============ SECTION 5 — Deployment Metrics ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">5</span>
        Deployment Metrics
        <span className="section-label-by">this run</span>
      </div>
      <div className="mb-2">
        <DeploymentMetricsCard metrics={metrics} />
      </div>

      {/* ============ SECTION 6 — Workflow History ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">6</span>
        Workflow History
        <span className="section-label-by">{history.length} executions</span>
      </div>
      <PhaseStatusCard
        icon="fa-clock-rotate-left"
        title="Previous Executions"
        subtitle="Earlier runs of this workflow for this project."
        className="mb-2"
      >
        <WorkflowHistoryPanel executions={history} />
      </PhaseStatusCard>

      {/* ============ SECTION 7 — Deployment Artifacts ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">7</span>
        Deployment Artifacts
        <span className="section-label-by">{artifacts.length} artifacts</span>
      </div>
      <PhaseStatusCard
        icon="fa-box-archive"
        title="Final Artifacts"
        subtitle="Everything generated across the workflow — view or download."
        status="completed"
        className="mb-2"
      >
        <ArtifactExplorer artifacts={artifacts} />
      </PhaseStatusCard>

      {/* ============ SECTION 8 — Next Actions ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">8</span>
        Next Actions
        <span className="section-label-by">where to go from here</span>
      </div>
      <div className="next-actions mb-2">
        <NextAction icon="fa-gauge-high" title="Open Project Dashboard" detail="Back to the project overview." onClick={() => navigate('/')} />
        <NextAction icon="fa-server" title="View Resources" detail="Browse the live infrastructure inventory." onClick={() => navigate('/infrastructure')} />
        <NextAction icon="fa-diagram-project" title="Start New Workflow" detail="Kick off another deployment workflow." onClick={() => navigate('/workflows')} />
        <NextAction icon="fa-file-arrow-down" title="Download Deployment Report" detail="Export a summary of this deployment." onClick={downloadReport} />
      </div>

      {/* ---- Completion footer ---- */}
      <div className="phase-footer">
        <p className="phase-footer-note">
          <i className="fa-solid fa-flag-checkered me-2" style={{ color: '#34d399' }} />
          Workflow completed — analysis → planning → Docker → Terraform → GitHub Actions → execution → live infrastructure.
        </p>
        <button type="button" className="bgrd btn px-4 py-2 phase-cta" onClick={() => navigate('/workflows')}>
          <i className="fa-solid fa-circle-plus me-2" />
          Start New Workflow
        </button>
      </div>
    </ContentContainer>
  );
}

function NextAction({ icon, title, detail, onClick }) {
  return (
    <button type="button" className="surface next-action" onClick={onClick}>
      <span className="next-action-ico"><i className={`fa-solid ${icon}`} /></span>
      <span className="next-action-body">
        <span className="next-action-title">{title}</span>
        <span className="next-action-detail">{detail}</span>
      </span>
      <i className="fa-solid fa-arrow-right next-action-arrow" />
    </button>
  );
}
