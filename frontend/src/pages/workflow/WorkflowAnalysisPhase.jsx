import { useWorkflowPhaseAnalysis } from '@/hooks/useWorkflowRun';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import EmptyState from '@/components/common/EmptyState';
import Skeleton from '@/components/common/Skeleton';

import AnalysisContextHeader from '@/components/workflow/analysis/AnalysisContextHeader';
import CustomerPortalPanel from '@/components/workflow/analysis/CustomerPortalPanel';
import CodeAnalysisPanel from '@/components/workflow/analysis/CodeAnalysisPanel';
import ArchitectureIntelligencePanel from '@/components/workflow/analysis/ArchitectureIntelligencePanel';
import InfrastructureRecommendationPanel from '@/components/workflow/analysis/InfrastructureRecommendationPanel';
import SecurityContainerizationPanel from '@/components/workflow/analysis/SecurityContainerizationPanel';

/**
 * WorkflowAnalysisPhase — the first executable workflow phase, opened by
 * resuming a workflow. Backed by REAL data: ONE request
 * (GET /api/workflows/:id/analysis) distributed to five sections of a single
 * phase (NOT five phases):
 *
 *   1. Customer Portal   2. Code Analysis   3. Architecture Intelligence
 *   4. Infrastructure Recommendations   5. Security & Containerization
 *
 * Read-only: the analysis already ran during project bootstrap. This surface
 * never restarts the workflow or re-runs analysis — it visualizes what the
 * backend already produced. Loading / error / empty states are explicit.
 *
 * @param {{ workflowId: string, workflow?: object }} props
 */
const SECTIONS = [
  { n: 1, label: 'Customer Portal', by: 'Business Summary' },
  { n: 2, label: 'Code Analysis', by: 'Code Analysis Agent' },
  { n: 3, label: 'Architecture Intelligence', by: 'Architecture Analysis' },
  { n: 4, label: 'Infrastructure Recommendations', by: 'Derived from analysis' },
  { n: 5, label: 'Security & Containerization', by: 'Security Guard' },
];

export default function WorkflowAnalysisPhase({ workflowId, workflow }) {
  const { data, loading, error, refetch } = useWorkflowPhaseAnalysis(workflowId);

  /* ── Hard failure: nothing to show ───────────────────────────────────────── */
  if (error && !data) {
    return (
      <EmptyState
        icon="fa-triangle-exclamation"
        title="Couldn't load the analysis"
        message={error.message || 'The workflow analysis could not be retrieved.'}
        action={
          <button className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={refetch}>
            <i className="fa-solid fa-rotate-right me-2" />
            Retry
          </button>
        }
      />
    );
  }

  /* ── First load: full-page skeleton ──────────────────────────────────────── */
  if (loading && !data) {
    return (
      <>
        <WorkflowTimeline current="analysis" navigable={false} />
        <HeaderSkeleton />
        <PanelSkeletons />
      </>
    );
  }

  const status = data?.status || 'RUNNING';
  const isRunning = status === 'RUNNING';
  const isFailed = status === 'FAILED';
  const isDone = status === 'DONE';

  return (
    <>
      <WorkflowTimeline
        current="analysis"
        navigable={false}
        statuses={{ analysis: isDone ? 'completed' : isFailed ? 'failed' : 'running' }}
      />

      <AnalysisContextHeader
        project={data?.projectInfo}
        status={status}
        lastUpdated={data?.lastUpdated || workflow?.updatedAt}
      />

      {isRunning && (
        <div className="surface d-flex align-items-center gap-2 mb-3" style={{ padding: '12px 16px' }}>
          <span className="spinner" />
          <span style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>
            Analysis is still completing for this repository — results will appear here once ready.
          </span>
        </div>
      )}

      {isFailed && (
        <div className="surface phase-card rail-failed mb-3">
          <div className="phase-card-head">
            <div className="d-flex align-items-center gap-3" style={{ minWidth: 0 }}>
              <span className="phase-step-chip" style={{ color: '#f87171' }}>
                <i className="fa-solid fa-circle-xmark" />
              </span>
              <div>
                <h3 className="card-title">Analysis failed</h3>
                <p className="phase-card-subtitle">
                  The project analysis did not complete. Re-run it from the project page.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {isRunning ? (
        <PanelSkeletons />
      ) : (
        <>
          <SectionLabel {...SECTIONS[0]} />
          <CustomerPortalPanel data={data?.customerPortal} />

          <SectionLabel {...SECTIONS[1]} />
          <CodeAnalysisPanel data={data?.codeAnalysis} />

          <SectionLabel {...SECTIONS[2]} />
          <ArchitectureIntelligencePanel data={data?.architecture} />

          <SectionLabel {...SECTIONS[3]} />
          <InfrastructureRecommendationPanel data={data?.infrastructureRecommendations} />

          <SectionLabel {...SECTIONS[4]} />
          <SecurityContainerizationPanel
            security={data?.securityAnalysis}
            containerization={data?.containerization}
          />
        </>
      )}
    </>
  );
}

/* ── Local presentational helpers ─────────────────────────────────────────── */

function SectionLabel({ n, label, by }) {
  return (
    <div className="section-label mt-4">
      <span className="section-label-chip">{n}</span>
      {label}
      <span className="section-label-by">{by}</span>
    </div>
  );
}

function HeaderSkeleton() {
  return (
    <div className="surface mb-3">
      <div className="d-flex align-items-center gap-3">
        <Skeleton width="48px" height={48} radius={12} />
        <div style={{ flex: 1 }}>
          <Skeleton width="40%" height={18} />
          <Skeleton width="30%" height={12} className="mt-2" />
        </div>
        <Skeleton width="90px" height={26} radius={20} />
      </div>
    </div>
  );
}

function PanelSkeletons() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <div className="surface mb-3" key={i}>
          <Skeleton width="32%" height={16} />
          <Skeleton width="100%" height={12} className="mt-3" />
          <Skeleton width="85%" height={12} className="mt-2" />
          <Skeleton width="60%" height={12} className="mt-2" />
        </div>
      ))}
    </>
  );
}
