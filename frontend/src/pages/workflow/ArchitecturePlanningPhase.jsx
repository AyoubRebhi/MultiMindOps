import { useState } from 'react';
import { Link } from 'react-router-dom';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import EmptyState from '@/components/common/EmptyState';
import ErrorState from '@/components/common/ErrorState';
import Skeleton from '@/components/common/Skeleton';
import ArchitecturePlanCard from '@/components/workflow/architecture/ArchitecturePlanCard';
import PlanComparisonTable from '@/components/workflow/architecture/PlanComparisonTable';
import { useArchitectureDecision } from '@/hooks/useWorkflowRun';
import { useToast } from '@/hooks/useToast';
import { workflowApi } from '@/services/api/workflowApi';

/**
 * ArchitecturePlanningPhase — the second executable workflow phase. Backed by
 * REAL data: GET .../architecture-decision returns the AI-generated plans (one
 * LLM call via PlannerAgent → GPT-5-mini, see Phase 7). The engineer reviews
 * and compares the plans, then selects ONE. Selection is persisted through the
 * backend (POST .../select-plan), which records PLAN_SELECTED and unblocks
 * Terraform Generation — the frontend never mutates workflow state itself.
 *
 * @param {{ workflowId: string, workflow: object, onAdvance?: () => void }} props
 *   onAdvance refreshes the parent workflow after a successful selection so the
 *   resume router reflects the new phase.
 */
export default function ArchitecturePlanningPhase({ workflowId, workflow, onAdvance }) {
  const projectId = workflow?.projectId;
  const toast = useToast();
  const { data, loading, error, refetch } = useArchitectureDecision(projectId, workflowId);

  // Selection: `selectingId` is the in-flight request (disables every card to
  // prevent duplicate submits); `optimisticId` reflects the just-persisted pick
  // until the authoritative refetch lands.
  const [selectingId, setSelectingId] = useState(null);
  const [optimisticId, setOptimisticId] = useState(null);

  const selectedId = optimisticId || data?.selectedPlanId || null;

  async function handleSelect(planId) {
    if (!projectId || selectingId || planId === selectedId) return;
    setSelectingId(planId);
    try {
      await workflowApi.selectPlan(projectId, workflowId, planId);
      setOptimisticId(planId);
      toast.success('Plan selected — workflow advanced to Docker Generation.');
      await refetch(); // re-read the authoritative selected_plan_id
      onAdvance?.(); // refresh the parent workflow (current_phase → PLAN_SELECTED)
    } catch (e) {
      toast.error(e?.message || 'Could not select the plan. Please try again.');
    } finally {
      setSelectingId(null);
    }
  }

  /* ── Hard transport failure (not a 404 "no plans yet") ───────────────────── */
  if (error && !data) {
    const noPlans = error?.status === 404;
    if (noPlans) {
      return (
        <PlanningShell workflow={workflow} status={workflow?.status}>
          <NoPlans projectId={projectId} onRetry={refetch} />
        </PlanningShell>
      );
    }
    return (
      <PlanningShell workflow={workflow} status="failed">
        <ErrorState
          title="Couldn't load architecture plans"
          message={error.message}
          onRetry={refetch}
        />
      </PlanningShell>
    );
  }

  /* ── First load ──────────────────────────────────────────────────────────── */
  if (loading && !data) {
    return (
      <PlanningShell workflow={workflow} status={workflow?.status}>
        <PlanSkeletons />
      </PlanningShell>
    );
  }

  const plans = data?.plans || [];
  if (!plans.length) {
    return (
      <PlanningShell workflow={workflow} status={workflow?.status}>
        <NoPlans projectId={projectId} onRetry={refetch} />
      </PlanningShell>
    );
  }

  const selectedPlan = plans.find((p) => p.id === selectedId);

  return (
    <PlanningShell workflow={workflow} status={workflow?.status} selected={!!selectedId}>
      {selectedId ? (
        <div className="surface d-flex align-items-start gap-3 mb-3" style={{ borderLeft: '3px solid #34d399' }}>
          <i className="fa-solid fa-circle-check" style={{ color: '#34d399', marginTop: 2 }} />
          <div style={{ fontSize: '.86rem' }}>
            <strong>{selectedPlan?.title || 'A plan'}</strong> is selected. The workflow has
            advanced — <strong>Docker Generation</strong> is now unlocked. You can change
            your choice below until you continue.
          </div>
        </div>
      ) : (
        <div className="surface d-flex align-items-center gap-2 mb-3" style={{ padding: '12px 16px' }}>
          <i className="fa-solid fa-circle-info" style={{ color: 'var(--tx3)' }} />
          <span style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>
            Review the AI-generated architecture options below and select one to advance the
            workflow.{' '}
            {data?.recommendedPlan && (
              <>
                Recommended:{' '}
                <strong>
                  {plans.find((p) => p.id === data.recommendedPlan)?.title || data.recommendedPlan}
                </strong>
                .
              </>
            )}
          </span>
        </div>
      )}

      <div className="section-label mt-2">
        <span className="section-label-chip">1</span>
        Recommended Architecture Plans
        <span className="section-label-by">PlannerAgent · GPT-5-mini</span>
      </div>

      <div className="row g-3">
        {plans.map((plan) => (
          <div className="col-md-6 col-xl-4" key={plan.id}>
            <ArchitecturePlanCard
              plan={plan}
              selected={plan.id === selectedId}
              selecting={selectingId === plan.id}
              disabled={!!selectingId}
              onSelect={() => handleSelect(plan.id)}
            />
          </div>
        ))}
      </div>

      <div className="section-label mt-4">
        <span className="section-label-chip">2</span>
        Plan Comparison
        <span className="section-label-by">Side-by-side trade-offs</span>
      </div>

      <PlanComparisonTable
        plans={plans}
        selectedId={selectedId}
        recommendedId={data?.recommendedPlan}
      />
    </PlanningShell>
  );
}

/* ── Layout shell: timeline + phase header + content ───────────────────────── */

function PlanningShell({ status, selected = false, children }) {
  return (
    <>
      <WorkflowTimeline
        current="planning"
        navigable={false}
        statuses={{
          analysis: 'completed',
          planning: selected ? 'completed' : 'running',
        }}
      />
      <WorkflowPhaseHeader
        icon="fa-sitemap"
        eyebrow="Phase 2 · Architecture Selection"
        title="Architecture Planning"
        subtitle="Review the AI-generated cloud architectures, compare the trade-offs and select one to provision."
        status={status}
      />
      {children}
    </>
  );
}

/* ── States ────────────────────────────────────────────────────────────────── */

function NoPlans({ projectId, onRetry }) {
  return (
    <EmptyState
      icon="fa-diagram-project"
      title="No architecture plans yet"
      message="The architecture-planning phase hasn't produced plans for this workflow yet. This usually means analysis is still completing — try again in a moment."
      action={
        <div className="d-flex gap-2">
          <button className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={onRetry}>
            <i className="fa-solid fa-rotate-right me-2" />
            Retry
          </button>
          {projectId && (
            <Link to={`/projects/${projectId}`} className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }}>
              <i className="fa-solid fa-folder-open me-2" />
              Open project
            </Link>
          )}
        </div>
      }
    />
  );
}

function PlanSkeletons() {
  return (
    <div className="row g-3">
      {[0, 1, 2].map((i) => (
        <div className="col-md-6 col-xl-4" key={i}>
          <div className="surface h-100">
            <Skeleton width="55%" height={18} />
            <Skeleton width="80%" height={12} className="mt-2" />
            <Skeleton width="40%" height={28} className="mt-3" />
            <Skeleton width="100%" height={12} className="mt-3" />
            <Skeleton width="100%" height={12} className="mt-2" />
            <Skeleton width="90%" height={12} className="mt-2" />
            <Skeleton width="100%" height={36} radius={10} className="mt-3" />
          </div>
        </div>
      ))}
    </div>
  );
}
