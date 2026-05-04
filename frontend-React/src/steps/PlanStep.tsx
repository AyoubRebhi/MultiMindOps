import { useState } from 'react'
import {
  ClipboardList,
  CheckCircle2,
  XCircle,
  Edit3,
  ChevronDown,
  ChevronRight,
  Package,
  Layers,
  Cpu,
  AlertTriangle,
} from 'lucide-react'
import { StepContainer } from '@/components/workflow/StepContainer'
import { LogViewer } from '@/components/workflow/LogViewer'
import { useWorkflowStore } from '@/store/workflowStore'
import { cn } from '@/lib/utils'
import type { PlanData, PlanValidationDecision } from '@/types'

// ── Plan data display ─────────────────────────────────────────────────────────

function PlanSection({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true)
  return (
    <div className={cn(
      'rounded-xl border overflow-hidden',
      'border-slate-200 dark:border-white/[0.06]',
      'bg-white dark:bg-surface-900',
    )}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'w-full flex items-center gap-2 px-4 py-3 text-left',
          'bg-slate-50 dark:bg-surface-800/40',
          'border-b border-slate-200 dark:border-white/[0.06]',
        )}
      >
        {open
          ? <ChevronDown  className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          : <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />}
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200 uppercase tracking-wider">
          {title}
        </span>
      </button>
      {open && <div className="p-4">{children}</div>}
    </div>
  )
}

function ArtifactBadge({ name, selected, onToggle }: { name: string; selected: boolean; onToggle?: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={!onToggle}
      className={cn(
        'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border',
        selected
          ? 'bg-brand-50 dark:bg-brand-600/20 border-brand-200 dark:border-brand-500/30 text-brand-700 dark:text-brand-300'
          : 'bg-slate-50 dark:bg-surface-800/50 border-slate-200 dark:border-white/[0.06] text-slate-500 dark:text-slate-400',
        onToggle && 'cursor-pointer hover:border-brand-300 dark:hover:border-brand-500/40',
      )}
    >
      <Package className="w-3 h-3 shrink-0" />
      {name}
    </button>
  )
}

function PlanDisplay({ plan, selectedArtifacts, onToggleArtifact }: {
  plan: PlanData
  selectedArtifacts?: string[]
  onToggleArtifact?: (art: string) => void
}) {
  const summary    = plan.summary ?? plan.reasoning_summary ?? plan.plan_description ?? ''
  const steps      = plan.steps ?? []
  const actions    = plan.actions ?? []
  const artifacts  = plan.artifacts ?? plan.required_artifacts ?? []
  const technologies = plan.technologies ?? []
  const complexity = plan.estimated_complexity

  return (
    <div className="space-y-4">
      {/* Summary */}
      {summary && (
        <div className={cn(
          'flex items-start gap-3 px-4 py-3 rounded-xl',
          'bg-brand-50 dark:bg-brand-600/10',
          'border border-brand-200 dark:border-brand-500/20',
        )}>
          <ClipboardList className="w-4 h-4 text-brand-500 shrink-0 mt-0.5" />
          <p className="text-sm text-brand-800 dark:text-brand-200 leading-relaxed">{summary}</p>
        </div>
      )}

      {/* Complexity badge */}
      {complexity && (
        <div className="flex items-center gap-2">
          <Cpu className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-xs text-slate-500 dark:text-slate-400">Complexity:</span>
          <span className={cn(
            'px-2 py-0.5 rounded-full text-xs font-medium',
            complexity === 'low'    && 'bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300',
            complexity === 'medium' && 'bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300',
            complexity === 'high'   && 'bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-300',
          )}>
            {complexity}
          </span>
        </div>
      )}

      {/* Technologies */}
      {technologies.length > 0 && (
        <PlanSection title="Technologies">
          <div className="flex flex-wrap gap-2">
            {technologies.map((t) => (
              <span
                key={String(t)}
                className="px-2 py-1 rounded-md text-xs font-medium bg-slate-100 dark:bg-surface-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-white/[0.06]"
              >
                {String(t)}
              </span>
            ))}
          </div>
        </PlanSection>
      )}

      {/* Steps / Actions */}
      {(steps.length > 0 || actions.length > 0) && (
        <PlanSection title="Execution Steps">
          <ol className="space-y-2">
            {(steps.length > 0 ? steps : actions).map((item, i) => (
              <li key={i} className="flex items-start gap-3 text-sm">
                <span className={cn(
                  'shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold mt-0.5',
                  'bg-brand-100 dark:bg-brand-600/20 text-brand-700 dark:text-brand-300',
                )}>
                  {i + 1}
                </span>
                <span className="text-slate-700 dark:text-slate-300 leading-relaxed">
                  {typeof item === 'string'
                    ? item
                    : (item as { description?: string }).description ?? JSON.stringify(item)}
                </span>
              </li>
            ))}
          </ol>
        </PlanSection>
      )}

      {/* Artifacts */}
      {artifacts.length > 0 && (
        <PlanSection title="Artifacts to Generate">
          <div className="flex flex-wrap gap-2">
            {artifacts.map((art) => (
              <ArtifactBadge
                key={String(art)}
                name={String(art)}
                selected={selectedArtifacts ? selectedArtifacts.includes(String(art)) : true}
                onToggle={onToggleArtifact ? () => onToggleArtifact(String(art)) : undefined}
              />
            ))}
          </div>
          {onToggleArtifact && (
            <p className="text-xs text-slate-400 dark:text-slate-600 mt-3">
              Click to toggle which artifacts to generate.
            </p>
          )}
        </PlanSection>
      )}

      {/* Technologies from plan.technologies (Layers icon) */}
      {plan.plan_variant && (
        <div className="flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
          <Layers className="w-3.5 h-3.5" />
          Plan variant: <span className="font-medium text-slate-600 dark:text-slate-300">{plan.plan_variant}</span>
        </div>
      )}
    </div>
  )
}

// ── Human validation panel ────────────────────────────────────────────────────

function HumanValidationPanel({
  onDecision,
  isLoading,
  rejectedMessage,
}: {
  onDecision: (d: PlanValidationDecision, feedback?: string) => void
  isLoading: boolean
  rejectedMessage?: string | null
}) {
  const [feedback, setFeedback] = useState('')
  const [activeDecision, setActiveDecision] = useState<PlanValidationDecision | null>(null)

  if (rejectedMessage) {
    return (
      <div className={cn(
        'flex items-start gap-3 px-4 py-3 rounded-xl',
        'bg-red-50 dark:bg-red-500/10',
        'border border-red-200 dark:border-red-500/20',
      )}>
        <XCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-medium text-red-700 dark:text-red-300">Plan Rejected</p>
          <p className="text-xs text-red-600/70 dark:text-red-400/60 mt-0.5">{rejectedMessage}</p>
        </div>
      </div>
    )
  }

  return (
    <div className={cn(
      'rounded-xl border p-4 space-y-4',
      'bg-white dark:bg-surface-900',
      'border-slate-200 dark:border-white/[0.06]',
    )}>
      <div className="flex items-start gap-3">
        <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-slate-800 dark:text-white">Human validation required</p>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Review the plan above and choose an action. Execution is paused until you decide.
          </p>
        </div>
      </div>

      {/* Feedback for modify */}
      {activeDecision === 'modified' && (
        <textarea
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder="Describe what you want changed in the plan…"
          rows={3}
          className={cn(
            'w-full rounded-xl px-3 py-2 text-sm resize-none focus:outline-none transition-colors',
            'bg-slate-50 dark:bg-surface-800/50',
            'border border-slate-200 dark:border-white/[0.08]',
            'focus:border-brand-400 dark:focus:border-brand-500/40',
            'text-slate-800 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-600',
          )}
        />
      )}

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => onDecision('approved')}
          disabled={isLoading}
          className="flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition-colors disabled:opacity-40"
        >
          <CheckCircle2 className="w-4 h-4" />
          Approve
        </button>

        <button
          onClick={() => {
            if (activeDecision === 'modified') {
              onDecision('modified', feedback)
            } else {
              setActiveDecision('modified')
            }
          }}
          disabled={isLoading}
          className={cn(
            'flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-colors disabled:opacity-40',
            'bg-white dark:bg-surface-800 border border-slate-200 dark:border-white/[0.08]',
            'text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-white/[0.05]',
          )}
        >
          <Edit3 className="w-4 h-4" />
          {activeDecision === 'modified' ? 'Submit Changes' : 'Request Changes'}
        </button>

        <button
          onClick={() => onDecision('rejected')}
          disabled={isLoading}
          className={cn(
            'flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-colors disabled:opacity-40',
            'text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10',
          )}
        >
          <XCircle className="w-4 h-4" />
          Reject
        </button>
      </div>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

interface Props {
  onApproveStandard: (approvedArtifacts: string[]) => void
  onApproveHuman:    (decision: PlanValidationDecision, feedback?: string) => void
  onBack:            () => void
  isLoading:         boolean
  rejectedMessage?:  string | null
}

export function PlanStep({
  onApproveStandard,
  onApproveHuman,
  onBack,
  isLoading,
  rejectedMessage,
}: Props) {
  const { planPreview, requiresHumanValidation } = useWorkflowStore()
  const plan = planPreview?.plan

  // Pre-select all artifacts from the plan
  const availableArtifacts = [
    ...(plan?.artifacts ?? []),
    ...(plan?.required_artifacts ?? []),
  ].map(String).filter(Boolean)

  const [selectedArtifacts, setSelectedArtifacts] = useState<string[]>(availableArtifacts)

  const toggleArtifact = (art: string) =>
    setSelectedArtifacts((prev) =>
      prev.includes(art) ? prev.filter((a) => a !== art) : [...prev, art],
    )

  if (!planPreview || !plan) {
    return (
      <StepContainer onBack={onBack} isLoading={isLoading} hideActions>
        <div className="flex items-center justify-center h-48 text-slate-400 dark:text-slate-600 text-sm">
          No plan data available.
        </div>
      </StepContainer>
    )
  }

  return (
    <StepContainer
      onBack={onBack}
      onApprove={requiresHumanValidation ? undefined : () => onApproveStandard(selectedArtifacts)}
      approveLabel="Approve Plan & Generate"
      approveIcon={<CheckCircle2 className="w-4 h-4" />}
      isLoading={isLoading}
    >
      <div className="max-w-3xl space-y-6">

        {/* Logs from plan preview */}
        {planPreview.logs?.length > 0 && (
          <div>
            <p className="text-xs font-medium text-slate-400 dark:text-slate-500 mb-2">Plan generation logs</p>
            <LogViewer logs={planPreview.logs} className="h-28" autoScroll={false} />
          </div>
        )}

        {/* Plan details */}
        <PlanDisplay
          plan={plan}
          selectedArtifacts={requiresHumanValidation ? undefined : selectedArtifacts}
          onToggleArtifact={requiresHumanValidation ? undefined : toggleArtifact}
        />

        {/* Human validation controls */}
        {requiresHumanValidation && (
          <HumanValidationPanel
            onDecision={onApproveHuman}
            isLoading={isLoading}
            rejectedMessage={rejectedMessage}
          />
        )}
      </div>
    </StepContainer>
  )
}
