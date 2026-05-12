import {
  Terminal,
  Container,
  Play,
  Layers,
  Ship,
  LayoutGrid,
  GitBranch,
  CheckCircle2,
  Lock,
  Check,
  Loader2,
  Network,
  Wrench,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  useWorkflowStore,
  WORKFLOW_STEPS,
  STEP_META,
  shouldShowCorrectorStep,
  type WorkflowStep,
} from '@/store/workflowStore'

// ── Step icon map ─────────────────────────────────────────────────────────────

const STEP_ICONS: Record<WorkflowStep, React.ElementType> = {
  INPUT:                 Terminal,
  ARCHITECTURE_DECISION: Network,
  INFRA:                 Container,
  DOCKER_BUILD:          Play,
  CORRECTOR_REVIEW:      Wrench,
  TERRAFORM:             Layers,
  KUBERNETES:            Ship,
  SUMMARY:               LayoutGrid,
  CICD:                  GitBranch,
  RESULT:                CheckCircle2,
}

// CORRECTOR_REVIEW is only displayed when the workflow phase indicates a
// build failure / active remediation. Otherwise it is hidden from the sidebar
// so normal successful builds don't show a redundant step.
function useVisibleSteps(currentPhase: string): WorkflowStep[] {
  const showCorrector = shouldShowCorrectorStep(currentPhase)
  return WORKFLOW_STEPS.filter(
    (s) => s !== 'CORRECTOR_REVIEW' || showCorrector,
  )
}

function getStepStatus(
  step: WorkflowStep,
  current: WorkflowStep,
  visibleSteps: WorkflowStep[],
  isGenerating: boolean,
): 'completed' | 'current' | 'generating' | 'locked' {
  const currentIdx = visibleSteps.indexOf(current)
  const stepIdx    = visibleSteps.indexOf(step)

  if (isGenerating && step === current) return 'generating'
  if (stepIdx < currentIdx) return 'completed'
  if (stepIdx === currentIdx) return 'current'
  return 'locked'
}

// ── Single step item ──────────────────────────────────────────────────────────

function StepItem({
  step,
  index,
  status,
  isCorrectorStep,
  onClick,
}: {
  step: WorkflowStep
  index: number
  status: ReturnType<typeof getStepStatus>
  isCorrectorStep: boolean
  onClick: () => void
}) {
  const Icon = STEP_ICONS[step]
  const { label, description } = STEP_META[step]

  const isClickable = status === 'completed' || status === 'current'

  return (
    <button
      disabled={!isClickable}
      onClick={onClick}
      className={cn(
        'w-full text-left flex items-start gap-3 px-3 py-3 rounded-xl transition-all',
        'border',
        isCorrectorStep && status === 'current'
          ? cn('bg-amber-500/8 border-amber-500/25')
          : status === 'current'
          ? cn('bg-brand-50 dark:bg-brand-600/15', 'border-brand-200 dark:border-brand-500/25')
          : status === 'completed'
          ? cn('border-transparent', 'hover:bg-slate-100 dark:hover:bg-white/[0.04]', 'hover:border-slate-200 dark:hover:border-white/[0.06]')
          : status === 'generating'
          ? cn('bg-amber-50 dark:bg-amber-500/10', 'border-amber-200 dark:border-amber-500/20')
          : cn('border-transparent opacity-40 cursor-not-allowed'),
      )}
    >
      {/* Circle with number / icon */}
      <div className={cn(
        'shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold mt-0.5',
        isCorrectorStep && status === 'current'
          ? 'bg-amber-500 text-slate-900'
          : status === 'current'
          ? 'bg-brand-600 text-white'
          : status === 'completed'
          ? 'bg-emerald-500 dark:bg-emerald-600 text-white'
          : status === 'generating'
          ? 'bg-amber-500 text-white'
          : 'bg-slate-200 dark:bg-surface-700 text-slate-400 dark:text-slate-500',
      )}>
        {status === 'completed' ? (
          <Check className="w-3.5 h-3.5" />
        ) : status === 'generating' ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <Icon className="w-3.5 h-3.5" />
        )}
      </div>

      {/* Labels */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <p className={cn(
            'text-sm font-medium leading-tight truncate',
            isCorrectorStep && status === 'current'
              ? 'text-amber-600 dark:text-amber-300'
              : status === 'current'
              ? 'text-brand-700 dark:text-brand-300'
              : status === 'completed'
              ? 'text-slate-700 dark:text-slate-200'
              : status === 'generating'
              ? 'text-amber-700 dark:text-amber-300'
              : 'text-slate-400 dark:text-slate-600',
          )}>
            {label}
          </p>
          {status === 'locked' && (
            <Lock className="w-3 h-3 text-slate-300 dark:text-slate-600 shrink-0" />
          )}
        </div>
        <p className={cn(
          'text-xs mt-0.5 leading-tight truncate',
          isCorrectorStep && status === 'current'
            ? 'text-amber-600/60 dark:text-amber-400/60'
            : status === 'current'
            ? 'text-brand-600/70 dark:text-brand-400/70'
            : 'text-slate-400 dark:text-slate-600',
        )}>
          {description}
        </p>
      </div>

      {/* Step number badge */}
      <span className={cn(
        'shrink-0 text-[10px] font-mono mt-0.5',
        status === 'locked'
          ? 'text-slate-300 dark:text-slate-700'
          : 'text-slate-300 dark:text-slate-600',
      )}>
        {String(index + 1).padStart(2, '0')}
      </span>
    </button>
  )
}

// ── Connector line ────────────────────────────────────────────────────────────

function Connector({ active }: { active: boolean }) {
  return (
    <div className="flex justify-start pl-[22px] py-0.5">
      <div className={cn(
        'w-0.5 h-3 rounded-full transition-colors',
        active
          ? 'bg-emerald-300 dark:bg-emerald-600/50'
          : 'bg-slate-200 dark:bg-surface-700',
      )} />
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function StepperSidebar() {
  const { currentStep, currentPhase, isGenerating, goToStep } = useWorkflowStore()
  const visibleSteps = useVisibleSteps(currentPhase)
  const currentIdx   = visibleSteps.indexOf(currentStep)

  return (
    <aside className={cn(
      'w-64 shrink-0 flex flex-col h-full',
      'bg-white dark:bg-surface-900',
      'border-r border-slate-200 dark:border-white/[0.06]',
      'overflow-y-auto',
    )}>
      {/* Header */}
      <div className="px-4 pt-5 pb-3 border-b border-slate-100 dark:border-white/[0.04]">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-600">
          Workflow Steps
        </p>
        <p className="text-[10px] text-slate-300 dark:text-slate-700 mt-0.5">
          {Math.max(currentIdx + 1, 1)} of {visibleSteps.length}
        </p>
      </div>

      {/* Steps */}
      <nav className="flex-1 px-3 py-3 space-y-0">
        {visibleSteps.map((step, i) => {
          const status = getStepStatus(step, currentStep, visibleSteps, isGenerating)
          const isCorrectorStep = step === 'CORRECTOR_REVIEW'
          return (
            <div key={step}>
              <StepItem
                step={step}
                index={i}
                status={status}
                isCorrectorStep={isCorrectorStep}
                onClick={() => {
                  if (status === 'completed' || status === 'current') {
                    goToStep(step)
                  }
                }}
              />
              {i < visibleSteps.length - 1 && (
                <Connector active={i < currentIdx} />
              )}
            </div>
          )
        })}
      </nav>

      {/* Progress bar */}
      <div className="px-4 py-4 border-t border-slate-100 dark:border-white/[0.04]">
        <div className="flex items-center justify-between text-[10px] text-slate-400 dark:text-slate-600 mb-1.5">
          <span>Progress</span>
          <span>
            {visibleSteps.length > 1
              ? Math.round((Math.max(currentIdx, 0) / (visibleSteps.length - 1)) * 100)
              : 0}%
          </span>
        </div>
        <div className="h-1 rounded-full bg-slate-100 dark:bg-surface-800">
          <div
            className="h-1 rounded-full bg-brand-500 transition-all duration-500"
            style={{
              width: `${visibleSteps.length > 1
                ? (Math.max(currentIdx, 0) / (visibleSteps.length - 1)) * 100
                : 0}%`,
            }}
          />
        </div>
      </div>
    </aside>
  )
}
