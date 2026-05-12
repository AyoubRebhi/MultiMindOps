/**
 * ArchitectureDecisionStep
 *
 * Unified replacement for PlanStep + CostEstimationStep.
 *
 * Shows 1–3 architecture strategy cards side-by-side, a comparison table,
 * and a hard confirmation gate before any infrastructure is generated.
 *
 * Flow:
 *   1. User inspects cards and comparison table.
 *   2. User clicks "Select This Plan" on one card.
 *   3. A confirmation banner appears at the bottom.
 *   4. User clicks "Confirm & Generate Infrastructure" → triggers Docker phase.
 */

import { useCallback, useState } from 'react'
import {
  Layers, AlertCircle, ChevronRight, RotateCcw,
  CheckCircle2, Info, Loader2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useWorkflowStore } from '@/store/workflowStore'
import { ArchitectureCard } from '@/components/architecture/ArchitectureCard'
import { ComparisonTable }  from '@/components/architecture/ComparisonTable'
import type { ArchitecturePlan } from '@/types'

// ── Loading skeleton ──────────────────────────────────────────────────────────

function CardSkeleton() {
  return (
    <div className="rounded-2xl border border-slate-700/40 bg-slate-800/40 p-5 animate-pulse space-y-4">
      <div className="flex justify-between">
        <div className="space-y-2">
          <div className="h-4 w-28 bg-slate-700 rounded" />
          <div className="h-3 w-48 bg-slate-800 rounded" />
        </div>
        <div className="h-5 w-14 bg-slate-700 rounded-full" />
      </div>
      <div className="h-14 bg-slate-900/40 rounded-xl" />
      <div className="flex gap-2 flex-wrap">
        {[1, 2, 3].map((i) => <div key={i} className="h-5 w-20 bg-slate-700 rounded-full" />)}
      </div>
      <div className="space-y-2">
        {[1, 2, 3].map((i) => <div key={i} className="h-3 bg-slate-800 rounded" />)}
      </div>
      <div className="h-9 bg-slate-700 rounded-xl" />
    </div>
  )
}

// ── Legacy single-plan view (backward compat for old tasks) ───────────────────

function LegacyPlanView({
  onConfirm,
  isLoading,
}: {
  onConfirm: () => void
  isLoading?: boolean
}) {
  const { task } = useWorkflowStore()
  const cost = task?.cost_estimation
  return (
    <div className={cn(
      'p-5 rounded-xl border border-slate-700/50 bg-slate-800/30 space-y-3',
    )}>
      <div className="flex items-center gap-2 text-amber-400">
        <Info className="w-4 h-4" />
        <p className="text-sm font-medium">Legacy task — single plan available</p>
      </div>
      <p className="text-xs text-slate-400">
        This task was created before multi-strategy support. Only one architecture plan is available.
        {cost && typeof cost.monthly_cost === 'number' && (
          <span className="ml-1 text-slate-300 font-medium">
            Estimated cost: ${cost.monthly_cost.toFixed(2)}/month.
          </span>
        )}
      </p>
      <button
        onClick={onConfirm}
        disabled={isLoading}
        className={cn(
          'flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-colors',
          !isLoading
            ? 'bg-brand-600 hover:bg-brand-700 text-white'
            : 'bg-slate-700 text-slate-400 cursor-not-allowed',
        )}
      >
        {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
        {isLoading ? 'Generating…' : 'Continue with this plan →'}
        {!isLoading && <ChevronRight className="w-4 h-4" />}
      </button>
    </div>
  )
}

// ── Confirmation banner ───────────────────────────────────────────────────────

function ConfirmationBanner({
  plan,
  onConfirm,
  onClear,
  isLoading,
}: {
  plan: ArchitecturePlan
  onConfirm: () => void
  onClear: () => void
  isLoading?: boolean
}) {
  return (
    <div className={cn(
      'sticky bottom-0 left-0 right-0 z-10',
      'px-6 py-4 rounded-xl border',
      'bg-slate-900/95 backdrop-blur-sm border-brand-500/30',
      'shadow-[0_-4px_24px_rgba(99,102,241,0.12)]',
    )}>
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <CheckCircle2 className="w-5 h-5 text-brand-400 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-white">
              {plan.title} selected — ${plan.monthly_cost.toFixed(2)}/month
            </p>
            <p className="text-xs text-slate-400 mt-0.5">
              Click confirm to generate your infrastructure artifacts.
              This action cannot be undone without restarting.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={onClear}
            disabled={isLoading}
            className={cn(
              'flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors',
              'border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-600',
              isLoading && 'opacity-40 cursor-not-allowed',
            )}
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Change
          </button>
          <button
            onClick={onConfirm}
            disabled={isLoading}
            className={cn(
              'flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-all',
              !isLoading
                ? 'bg-brand-600 hover:bg-brand-700 text-white shadow-md shadow-brand-600/20'
                : 'bg-slate-700 text-slate-400 cursor-not-allowed',
            )}
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <ChevronRight className="w-4 h-4" />
            )}
            {isLoading ? 'Generating Infrastructure…' : 'Confirm & Generate Infrastructure'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  /** Called with the chosen plan ID — triggers /select-plan then updates store */
  onSelectPlan: (planId: string) => Promise<void>
  /** Called after confirmation — triggers /run-docker → navigates to INFRA */
  onConfirm: () => Promise<void>
  onBack: () => void
  isLoading?: boolean
  isGenerating?: boolean
}

// ── Main component ────────────────────────────────────────────────────────────

export function ArchitectureDecisionStep({
  onSelectPlan,
  onConfirm,
  onBack,
  isLoading,
  isGenerating,
}: Props) {
  const { architectureDecision, selectedPlanId, task } = useWorkflowStore()
  const [localSelectedId, setLocalSelectedId] = useState<string | undefined>(selectedPlanId)
  const [selectingId, setSelectingId] = useState<string | null>(null)

  const plans = architectureDecision?.plans ?? []
  const recommendedId = architectureDecision?.recommended_plan ?? 'balanced'
  const hasLegacyData = !architectureDecision && (task?.plan || task?.cost_estimation)

  const handleSelect = useCallback(async (planId: string) => {
    if (selectingId || isLoading) return
    setSelectingId(planId)
    try {
      await onSelectPlan(planId)
      setLocalSelectedId(planId)
    } finally {
      setSelectingId(null)
    }
  }, [onSelectPlan, selectingId, isLoading])

  const handleClearSelection = useCallback(() => {
    setLocalSelectedId(undefined)
  }, [])

  const selectedPlan = plans.find((p) => p.id === (localSelectedId ?? selectedPlanId))

  // Determine what to render
  const isDataLoading = isLoading && !plans.length && !hasLegacyData

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {/* Header */}
        <div className={cn(
          'flex items-start gap-3 px-4 py-3 rounded-xl',
          'bg-brand-500/5 border border-brand-500/15',
        )}>
          <Layers className="w-4 h-4 text-brand-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-brand-300">
              AI Architecture Advisory — Choose Your Deployment Strategy
            </p>
            <p className="text-xs text-brand-400/60 mt-0.5">
              Your AI cloud architect generated multiple deployment strategies.
              Compare cost, availability, and scalability before committing.
              Infrastructure generation only starts after your explicit confirmation.
            </p>
          </div>
        </div>

        {/* Loading state */}
        {isDataLoading && (
          <div className="space-y-4">
            <LoadingBanner />
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <CardSkeleton />
              <CardSkeleton />
              <CardSkeleton />
            </div>
          </div>
        )}

        {/* Legacy fallback */}
        {!isDataLoading && hasLegacyData && (
          <LegacyPlanView onConfirm={onConfirm} isLoading={isGenerating} />
        )}

        {/* Multi-strategy view */}
        {!isDataLoading && plans.length > 0 && (
          <>
            {/* Strategy cards */}
            <div className={cn(
              'grid gap-4',
              plans.length === 1 ? 'grid-cols-1 max-w-sm' :
              plans.length === 2 ? 'grid-cols-1 md:grid-cols-2' :
              'grid-cols-1 md:grid-cols-3',
            )}>
              {plans.map((plan) => (
                <ArchitectureCard
                  key={plan.id}
                  plan={plan}
                  isRecommended={plan.id === recommendedId}
                  isSelected={plan.id === (localSelectedId ?? selectedPlanId)}
                  onSelect={() => handleSelect(plan.id)}
                  isLoading={selectingId === plan.id}
                />
              ))}
            </div>

            {/* Selection hint */}
            {!selectedPlan && (
              <div className={cn(
                'flex items-center gap-2 px-4 py-2.5 rounded-lg',
                'bg-amber-500/5 border border-amber-500/15 text-amber-400/80',
              )}>
                <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                <p className="text-xs">
                  Select a deployment strategy above to proceed. Infrastructure generation
                  will not start until you confirm.
                </p>
              </div>
            )}

            {/* Comparison table */}
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
                Side-by-Side Comparison
              </h3>
              <ComparisonTable
                plans={plans}
                selectedPlanId={localSelectedId ?? selectedPlanId}
              />
            </section>
          </>
        )}

        {/* No data and not loading */}
        {!isDataLoading && !hasLegacyData && plans.length === 0 && (
          <div className={cn(
            'flex items-start gap-3 px-4 py-4 rounded-xl',
            'bg-amber-500/5 border border-amber-500/15',
          )}>
            <AlertCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-amber-300">No architecture data available</p>
              <p className="text-xs text-amber-400/60 mt-1">
                Architecture strategies could not be loaded. Go back and re-run the analysis.
              </p>
              <button
                onClick={onBack}
                className="mt-2 text-xs text-amber-400 underline hover:text-amber-300"
              >
                ← Back to input
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Sticky confirmation banner (only when a plan is selected) */}
      {selectedPlan && !hasLegacyData && (
        <ConfirmationBanner
          plan={selectedPlan}
          onConfirm={onConfirm}
          onClear={handleClearSelection}
          isLoading={isGenerating}
        />
      )}
    </div>
  )
}

// ── Loading banner ────────────────────────────────────────────────────────────

function LoadingBanner() {
  return (
    <div className={cn(
      'flex items-center gap-3 px-4 py-3 rounded-xl',
      'bg-brand-500/5 border border-brand-500/15',
    )}>
      <Loader2 className="w-4 h-4 text-brand-400 animate-spin shrink-0" />
      <div>
        <p className="text-sm font-semibold text-brand-300">
          AI architect is analysing your project…
        </p>
        <p className="text-xs text-brand-400/60 mt-0.5">
          Generating deployment strategies and estimating AWS costs. This takes 20–60 seconds.
        </p>
      </div>
    </div>
  )
}
