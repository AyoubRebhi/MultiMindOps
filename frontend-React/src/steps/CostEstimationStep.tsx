import { ChevronRight, DollarSign, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useWorkflowStore } from '@/store/workflowStore'
import { CostSummaryCard }     from '@/components/cost/CostSummaryCard'
import { CostBreakdownChart }  from '@/components/cost/CostBreakdownChart'
import { OptimizationTipsPanel } from '@/components/cost/OptimizationTipsPanel'
import { AssumptionsPanel }    from '@/components/cost/AssumptionsPanel'

// ── Types matching backend cost_estimation output ─────────────────────────────

interface CostEstimation {
  monthly_cost: number
  cost_profile: string
  breakdown?: Record<string, number>
  optimization_tips?: unknown[]
  assumptions?: unknown[]
}

interface Props {
  onContinue: () => void
  onBack: () => void
  isPhaseLoading?: boolean
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CostEstimationStep({ onContinue, onBack, isPhaseLoading }: Props) {
  const { task } = useWorkflowStore()

  // Resolve cost estimation data from task — may live in multiple places
  const rawCost = (task?.cost_estimation
    ?? (task?.result as Record<string, unknown> | undefined)?.cost_estimation
    ?? (task?.plan as Record<string, unknown> | undefined)?.cost_estimation
  ) as CostEstimation | undefined

  const hasCost = rawCost && typeof rawCost.monthly_cost === 'number'

  const breakdown     = rawCost?.breakdown ?? {}
  const tips          = (rawCost?.optimization_tips ?? []) as unknown[]
  const assumptions   = (rawCost?.assumptions ?? []) as unknown[]

  return (
    <div className="flex flex-col h-full overflow-y-auto p-6 gap-6">

      {/* ── Header banner ──────────────────────────────────────────────────── */}
      <div className={cn(
        'flex items-start gap-3 px-4 py-3 rounded-xl',
        'bg-emerald-500/5 border border-emerald-500/15',
      )}>
        <DollarSign className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-emerald-300">AWS Cost Estimation — Pre-Approval Review</p>
          <p className="text-xs text-emerald-400/60 mt-0.5">
            AI-generated monthly cost breakdown based on your architecture plan.
            Review and approve before infrastructure artifacts are generated.
            On-demand pricing shown — reserved instances typically save 40–60%.
          </p>
        </div>
      </div>

      {!hasCost ? (
        /* ── No cost data ──────────────────────────────────────────────────── */
        <div className={cn(
          'flex items-start gap-3 px-4 py-3 rounded-xl',
          'bg-amber-500/5 border border-amber-500/15',
        )}>
          <AlertCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-300">Cost data not available</p>
            <p className="text-xs text-amber-400/60 mt-0.5">
              Cost estimation was not generated for this task. You can still continue to the Docker build step.
            </p>
          </div>
        </div>
      ) : (
        <>
          {/* ── Summary card ─────────────────────────────────────────────────── */}
          <section>
            <CostSummaryCard
              monthlyCost={rawCost!.monthly_cost}
              costProfile={rawCost!.cost_profile ?? 'unknown'}
            />
          </section>

          {/* ── Breakdown chart ───────────────────────────────────────────────── */}
          {Object.keys(breakdown).length > 0 && (
            <section className={cn(
              'p-5 rounded-xl border border-slate-700/50',
              'bg-slate-800/30',
            )}>
              <CostBreakdownChart breakdown={breakdown} />
            </section>
          )}

          {/* ── Optimization tips ─────────────────────────────────────────────── */}
          {tips.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
                Optimization Opportunities
              </h3>
              <OptimizationTipsPanel tips={tips as never[]} />
            </section>
          )}

          {/* ── Pricing assumptions ───────────────────────────────────────────── */}
          {assumptions.length > 0 && (
            <section>
              <AssumptionsPanel assumptions={assumptions as never[]} />
            </section>
          )}
        </>
      )}

      {/* ── Decision gate ──────────────────────────────────────────────────── */}
      <div className={cn(
        'px-4 py-3 rounded-xl text-xs',
        'bg-slate-800/40 border border-slate-700/50',
        'text-slate-400',
      )}>
        <span className="font-semibold text-slate-300">Decision gate:</span>{' '}
        Review the estimated costs above. Clicking "Approve &amp; Generate Infrastructure" will
        trigger the AI architect to generate your Dockerfile, docker-compose, and all companion
        files. You will review the artifacts before the Docker build starts.
      </div>

      {/* ── Action bar ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between pt-2 mt-auto">
        <button
          onClick={onBack}
          className={cn(
            'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
            'border border-slate-200 dark:border-white/[0.06]',
            'text-slate-600 dark:text-slate-400',
            'hover:bg-slate-100 dark:hover:bg-white/[0.04]',
          )}
        >
          ← Back to Plan
        </button>

        <button
          onClick={onContinue}
          disabled={isPhaseLoading}
          className={cn(
            'flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-colors',
            !isPhaseLoading
              ? 'bg-brand-600 hover:bg-brand-700 text-white'
              : 'bg-slate-200 dark:bg-surface-700 text-slate-400 cursor-not-allowed',
          )}
        >
          {isPhaseLoading ? 'Generating Infrastructure…' : 'Approve & Generate Infrastructure'}
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}
