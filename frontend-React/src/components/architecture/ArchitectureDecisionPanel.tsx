import { useMemo, useState } from 'react'
import { Layers, RefreshCcw, Loader2, AlertTriangle, CheckCircle2 } from 'lucide-react'
import {
  useArchitectureDecision,
  useSelectPlan,
  useStartWorkflow,
} from '@/hooks/useProjects'
import { ArchitectureCard } from './ArchitectureCard'
import { ComparisonTable } from './ComparisonTable'
import { cn } from '@/lib/utils'
import type { ArchitecturePlan } from '@/types'
import type { WorkflowResponse } from '@/types/project'

interface Props {
  projectId: string
  /** The most recent workflow for the project, or undefined if none exists yet. */
  workflow?: WorkflowResponse
  /** Whether the caller can submit a plan selection (UI mirrors backend authz). */
  canSelect: boolean
  /** Whether the caller can start/regenerate workflows (DEVELOPER+). */
  canRegenerate: boolean
}

/**
 * Central architecture-decision experience.
 *
 * Composes three lanes:
 *  1. Side-by-side strategy cards (cost, scalability, AWS services, tradeoffs)
 *  2. A comparison matrix (multi-AZ, autoscaling, read replicas, etc.)
 *  3. The selection + regeneration controls
 *
 * The component intentionally renders nothing if no decision exists yet —
 * the empty state belongs to the parent (which knows whether the user can
 * start a workflow).
 */
export function ArchitectureDecisionPanel({
  projectId,
  workflow,
  canSelect,
  canRegenerate,
}: Props) {
  const workflowId = workflow?.id ?? null
  const { data, isLoading, error, refetch } = useArchitectureDecision(projectId, workflowId)
  const selectPlan = useSelectPlan(projectId, workflowId ?? '')
  const startWorkflow = useStartWorkflow(projectId)

  const [pendingPlanId, setPendingPlanId] = useState<string | null>(null)

  const plans: ArchitecturePlan[] = useMemo(
    () => (data?.plans ?? []) as ArchitecturePlan[],
    [data],
  )
  const recommended = data?.recommended_plan ?? 'balanced'
  const selectedPlanId = data?.selected_plan_id ?? null

  if (!workflow) {
    return <EmptyState canRegenerate={canRegenerate} onStart={() => undefined} />
  }

  if (isLoading) {
    return <SkeletonCards />
  }

  if (error || !data) {
    // 404 from a workflow that hasn't reached planner yet — treat as awaiting.
    const status = (error as { response?: { status?: number } })?.response?.status
    if (status === 404) {
      return (
        <AwaitingState
          workflowId={workflow.id}
          status={workflow.status}
          phase={workflow.current_phase ?? 'ARCHITECTURE_DECISION'}
        />
      )
    }
    return (
      <div className="p-4 rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10 text-sm text-red-700 dark:text-red-300">
        Failed to load architecture decision: {(error as Error)?.message}
      </div>
    )
  }

  async function handleSelect(planId: string) {
    if (!canSelect || selectPlan.isPending) return
    setPendingPlanId(planId)
    try {
      await selectPlan.mutateAsync(planId)
      // Refetch to pick up the newly stamped selected_plan_id from backend.
      await refetch()
    } finally {
      setPendingPlanId(null)
    }
  }

  async function handleRegenerate() {
    if (!canRegenerate || startWorkflow.isPending) return
    const prompt = window.prompt(
      'Describe what you want the new strategies optimized for:',
      'Regenerate architecture strategies with the same intent',
    )
    if (!prompt) return
    await startWorkflow.mutateAsync({ prompt })
  }

  return (
    <div className="space-y-5">
      <Header
        selectedPlanId={selectedPlanId}
        recommendedId={recommended}
        canRegenerate={canRegenerate}
        regenerating={startWorkflow.isPending}
        onRegenerate={handleRegenerate}
      />

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {plans.map((plan) => (
          <ArchitectureCard
            key={plan.id}
            plan={plan}
            isRecommended={plan.id === recommended}
            isSelected={plan.id === selectedPlanId}
            isLoading={pendingPlanId === plan.id}
            onSelect={() => canSelect && handleSelect(plan.id)}
          />
        ))}
      </div>

      {plans.length > 1 && (
        <details className="rounded-xl border border-slate-200 dark:border-white/[0.06] bg-white dark:bg-surface-800/40" open>
          <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-700 dark:text-slate-300">
            Side-by-side comparison
          </summary>
          <div className="px-4 pb-4">
            <ComparisonTable plans={plans} selectedPlanId={selectedPlanId ?? undefined} />
          </div>
        </details>
      )}

      {selectPlan.error && (
        <div className="p-3 rounded-lg text-xs bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-500/30">
          {(selectPlan.error as Error).message}
        </div>
      )}

      {!canSelect && (
        <div className="p-3 rounded-lg text-xs bg-amber-50 dark:bg-amber-500/10 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-500/30 flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          You don&apos;t have permission to select a plan on this project. Ask a
          CLOUD_ARCHITECT or OWNER.
        </div>
      )}
    </div>
  )
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function Header({
  selectedPlanId,
  recommendedId,
  canRegenerate,
  regenerating,
  onRegenerate,
}: {
  selectedPlanId: string | null
  recommendedId: string
  canRegenerate: boolean
  regenerating: boolean
  onRegenerate: () => void
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-brand-600 dark:text-brand-400" />
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            Architecture decision
          </h2>
          {selectedPlanId ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 text-[10px] border border-emerald-200 dark:border-emerald-500/30">
              <CheckCircle2 className="w-3 h-3" />
              {selectedPlanId} selected
            </span>
          ) : (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 text-[10px] border border-amber-200 dark:border-amber-500/30">
              awaiting selection · recommended: {recommendedId}
            </span>
          )}
        </div>
        <p className="text-xs text-slate-500 mt-1 max-w-2xl">
          Compare the generated strategies side-by-side. Picking a plan promotes
          it into the workflow and unblocks Terraform, Kubernetes, and CI/CD
          phases for this project.
        </p>
      </div>
      {canRegenerate && (
        <button
          onClick={onRegenerate}
          disabled={regenerating}
          className={cn(
            'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium',
            'border border-slate-200 dark:border-white/[0.08]',
            'bg-white dark:bg-surface-900/40 text-slate-700 dark:text-slate-300',
            'hover:bg-slate-50 dark:hover:bg-white/[0.04]',
            'disabled:opacity-50 disabled:cursor-not-allowed shrink-0',
          )}
        >
          {regenerating ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <RefreshCcw className="w-3.5 h-3.5" />
          )}
          Regenerate plans
        </button>
      )}
    </div>
  )
}

function SkeletonCards() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="h-72 rounded-2xl border border-slate-200 dark:border-white/[0.06] bg-white dark:bg-surface-800/40 animate-pulse"
        />
      ))}
    </div>
  )
}

function EmptyState({
  canRegenerate,
}: {
  canRegenerate: boolean
  onStart: () => void
}) {
  return (
    <div className="p-6 rounded-xl text-center border border-dashed border-slate-200 dark:border-white/[0.08]">
      <Layers className="w-8 h-8 mx-auto text-slate-300 dark:text-slate-700 mb-3" />
      <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
        No architecture decision yet
      </div>
      <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto">
        Start a workflow from the Workflows tab — the platform will analyze the
        repository and generate cost-ranked strategies for you to compare.
        {canRegenerate ? '' : ' Your role does not allow starting workflows.'}
      </p>
    </div>
  )
}

function AwaitingState({
  workflowId,
  status,
  phase,
}: {
  workflowId: string
  status: string
  phase: string
}) {
  return (
    <div className="p-6 rounded-xl border border-slate-200 dark:border-white/[0.06] bg-white dark:bg-surface-800/40">
      <div className="flex items-center gap-2">
        <Loader2 className="w-4 h-4 animate-spin text-brand-600 dark:text-brand-400" />
        <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
          Strategies still being generated…
        </span>
      </div>
      <p className="text-xs text-slate-500 mt-1">
        Workflow <span className="font-mono">{workflowId.slice(0, 8)}…</span> is in
        phase <code className="text-[11px]">{phase}</code> (status: {status}).
        Plans will appear here as soon as the planner finishes.
      </p>
    </div>
  )
}
