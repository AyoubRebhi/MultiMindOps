import {
  CheckCircle2,
  Loader2,
  XCircle,
  Compass,
  Boxes,
  Rocket,
  ShieldCheck,
  Server,
  ArrowRight,
  Lightbulb,
  Play,
  Lock,
} from 'lucide-react'
import { cn } from '@/lib/utils'

/* eslint-disable react-refresh/only-export-components */

// ── Shared types ────────────────────────────────────────────────────────────
// Self-contained on purpose: this module is reusable across any surface that
// exposes a `phases_state`-shaped record, without coupling to WorkflowPanel.

export type PhaseStatus = 'completed' | 'failed' | 'running' | 'awaiting_input' | 'not_started'

export interface GuidancePhaseEntry {
  status?: string
}
export type GuidancePhasesState = Record<string, GuidancePhaseEntry>

function statusOf(s: GuidancePhasesState, key: string): PhaseStatus {
  const v = s[key]?.status
  if (v === 'completed' || v === 'failed' || v === 'running' || v === 'awaiting_input') return v
  return 'not_started'
}

/** Granular phases that can be triggered with a single click from the panel. */
export type RunnablePhase = 'TERRAFORM_GENERATION' | 'TERRAFORM_VALIDATION' | 'TERRAFORM_PLAN'

// ── Phase explanations (Task 3) ─────────────────────────────────────────────
// Concise, one-line descriptions. Kept short on purpose.

export const PHASE_EXPLANATIONS: Record<string, string> = {
  ARCHITECTURE_DECISION:  'Analyzes the repository and proposes deployment strategies.',
  PLAN_SELECTED:          'Locks in the selected strategy as the architecture decision.',
  TERRAFORM_GENERATION:   'Generates Terraform (.tf) files for the chosen plan.',
  TERRAFORM_VALIDATION:   'Runs terraform validate to confirm the configuration is well-formed.',
  TERRAFORM_PLAN:         'Creates an execution plan and predicts which cloud resources will be created.',
  INFRASTRUCTURE_SUMMARY: 'Shows a human-readable overview of the planned infrastructure.',
  DOCKER:                 'Generates the Dockerfile and container configuration.',
  KUBERNETES:             'Generates Kubernetes manifests for the workload.',
  CICD:                   'Generates the CI/CD pipeline definition.',
  VALIDATION:             'Runs security and policy checks across the generated artifacts.',
}

// ── Guidance computation (Task 1) ───────────────────────────────────────────

/** Ordered granular phases that drive the guided Discovery → Infrastructure flow. */
export const GUIDED_SEQUENCE = [
  'ARCHITECTURE_DECISION',
  'PLAN_SELECTED',
  'TERRAFORM_GENERATION',
  'TERRAFORM_VALIDATION',
  'TERRAFORM_PLAN',
] as const

const SHORT_LABEL: Record<string, string> = {
  ARCHITECTURE_DECISION: 'Analysis',
  PLAN_SELECTED:         'Architecture',
  TERRAFORM_GENERATION:  'Terraform generation',
  TERRAFORM_VALIDATION:  'Terraform validation',
  TERRAFORM_PLAN:        'Terraform plan',
}
function shortLabel(p: string): string {
  return SHORT_LABEL[p] ?? p
}

function runnable(p: string): RunnablePhase | undefined {
  return p === 'TERRAFORM_GENERATION' || p === 'TERRAFORM_VALIDATION' || p === 'TERRAFORM_PLAN'
    ? p
    : undefined
}

/** Per-phase: the "just completed" status text + the recommended next step. */
interface GuidanceStep {
  completeLabel: string
  nextLabel: string
  nextPhase?: RunnablePhase
  nextHint?: string
}

const GUIDANCE_BY_PHASE: Record<string, GuidanceStep> = {
  ARCHITECTURE_DECISION: {
    completeLabel: 'Analysis Complete',
    nextLabel: 'Generate Architecture',
    nextHint: 'Select a deployment strategy in the Architecture tab.',
  },
  PLAN_SELECTED: {
    completeLabel: 'Architecture Complete',
    nextLabel: 'Generate Terraform',
    nextPhase: 'TERRAFORM_GENERATION',
  },
  TERRAFORM_GENERATION: {
    completeLabel: 'Terraform Generated',
    nextLabel: 'Validate Terraform',
    nextPhase: 'TERRAFORM_VALIDATION',
  },
  TERRAFORM_VALIDATION: {
    completeLabel: 'Terraform Validated',
    nextLabel: 'Generate Plan',
    nextPhase: 'TERRAFORM_PLAN',
  },
  TERRAFORM_PLAN: {
    completeLabel: 'Plan Complete',
    nextLabel: 'Review Infrastructure Summary',
    nextHint: 'Scroll down to the Infrastructure Summary below.',
  },
}

/** Explanation of the step that comes AFTER the given completed phase. */
const NEXT_EXPLANATION: Record<string, string> = {
  ARCHITECTURE_DECISION: PHASE_EXPLANATIONS.PLAN_SELECTED,
  PLAN_SELECTED:         PHASE_EXPLANATIONS.TERRAFORM_GENERATION,
  TERRAFORM_GENERATION:  PHASE_EXPLANATIONS.TERRAFORM_VALIDATION,
  TERRAFORM_VALIDATION:  PHASE_EXPLANATIONS.TERRAFORM_PLAN,
  TERRAFORM_PLAN:        PHASE_EXPLANATIONS.INFRASTRUCTURE_SUMMARY,
}

export type GuidanceState = 'idle' | 'running' | 'failed' | 'actionable' | 'done'

export interface Guidance {
  state: GuidanceState
  statusLabel: string
  statusDetail: string
  nextLabel: string
  nextPhase?: RunnablePhase
  nextHint?: string
  /** The phase the status/explanation refers to. */
  activePhaseKey: string
}

/**
 * Derive "where you are / what's next" from a workflow's phases_state.
 *
 * Precedence: a running phase (wait) → a failed phase (retry) → the last
 * completed phase (recommend its next step) → nothing started (run analysis).
 */
export function computeGuidance(s: GuidancePhasesState): Guidance {
  const running = GUIDED_SEQUENCE.find((p) => statusOf(s, p) === 'running')
  if (running) {
    return {
      state: 'running',
      statusLabel: `${shortLabel(running)} running…`,
      statusDetail: PHASE_EXPLANATIONS[running] ?? '',
      nextLabel: 'Wait for the current phase to finish',
      activePhaseKey: running,
    }
  }

  const failed = GUIDED_SEQUENCE.find((p) => statusOf(s, p) === 'failed')
  if (failed) {
    return {
      state: 'failed',
      statusLabel: `${shortLabel(failed)} failed`,
      statusDetail: PHASE_EXPLANATIONS[failed] ?? '',
      nextLabel: `Retry ${shortLabel(failed)}`,
      nextPhase: runnable(failed),
      nextHint: runnable(failed) ? undefined : 'Re-run the phase from the controls below.',
      activePhaseKey: failed,
    }
  }

  // Walk the sequence; stop at the first non-completed phase.
  let lastCompleted: string | null = null
  for (const p of GUIDED_SEQUENCE) {
    if (statusOf(s, p) === 'completed') lastCompleted = p
    else break
  }

  if (!lastCompleted) {
    return {
      state: 'idle',
      statusLabel: 'Not started',
      statusDetail: PHASE_EXPLANATIONS.ARCHITECTURE_DECISION,
      nextLabel: 'Run Analysis',
      nextHint: 'Start a workflow to analyze the repository.',
      activePhaseKey: 'ARCHITECTURE_DECISION',
    }
  }

  const step = GUIDANCE_BY_PHASE[lastCompleted]
  const isLast = lastCompleted === GUIDED_SEQUENCE[GUIDED_SEQUENCE.length - 1]
  return {
    state: isLast ? 'done' : 'actionable',
    statusLabel: step.completeLabel,
    statusDetail: NEXT_EXPLANATION[lastCompleted] ?? '',
    nextLabel: step.nextLabel,
    nextPhase: step.nextPhase,
    nextHint: step.nextHint,
    activePhaseKey: lastCompleted,
  }
}

// ── Guidance panel (Task 1) ─────────────────────────────────────────────────

interface GuidancePanelProps {
  phasesState: GuidancePhasesState
  canRun?: boolean
  /** When supplied, a runnable next step renders a one-click action button. */
  onRunPhase?: (phase: RunnablePhase) => void
  isRunning?: boolean
  className?: string
}

export function WorkflowGuidancePanel({
  phasesState,
  canRun = true,
  onRunPhase,
  isRunning = false,
  className,
}: GuidancePanelProps) {
  const g = computeGuidance(phasesState)

  const tone =
    g.state === 'failed'
      ? 'border-red-200 dark:border-red-500/30 bg-red-50/60 dark:bg-red-500/[0.06]'
      : g.state === 'done'
        ? 'border-emerald-200 dark:border-emerald-500/30 bg-emerald-50/60 dark:bg-emerald-500/[0.06]'
        : 'border-brand-200 dark:border-brand-500/25 bg-brand-50/60 dark:bg-brand-600/[0.08]'

  const StatusIcon =
    g.state === 'failed' ? XCircle : g.state === 'running' ? Loader2 : g.state === 'done' ? CheckCircle2 : Lightbulb
  const iconTone =
    g.state === 'failed'
      ? 'text-red-500'
      : g.state === 'done'
        ? 'text-emerald-500'
        : g.state === 'running'
          ? 'text-brand-500'
          : 'text-brand-500'

  const showButton = !!g.nextPhase && !!onRunPhase && g.state !== 'running' && g.state !== 'done'

  return (
    <div className={cn('rounded-xl border p-4 space-y-2.5', tone, className)}>
      {/* Current status */}
      <div className="flex items-center gap-2">
        <StatusIcon className={cn('w-4 h-4 shrink-0', iconTone, g.state === 'running' && 'animate-spin')} />
        <span className="text-sm font-semibold text-slate-900 dark:text-white">{g.statusLabel}</span>
      </div>

      {/* Short explanation */}
      {g.statusDetail && (
        <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">{g.statusDetail}</p>
      )}

      {/* Recommended next action */}
      <div className="flex items-center gap-2 flex-wrap pt-0.5">
        <ArrowRight className="w-3.5 h-3.5 text-brand-500 shrink-0" />
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
          Next: {g.nextLabel}
        </span>
        {showButton && (
          <button
            onClick={() => onRunPhase!(g.nextPhase!)}
            disabled={!canRun || isRunning}
            title={!canRun ? 'Read-only role' : undefined}
            className={cn(
              'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors',
              'bg-brand-600 hover:bg-brand-500 text-white',
              'disabled:opacity-50 disabled:cursor-not-allowed',
            )}
          >
            {isRunning ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
            {g.nextLabel}
          </button>
        )}
        {!canRun && (
          <span className="inline-flex items-center gap-1 text-[11px] text-slate-400">
            <Lock className="w-3 h-3" /> read-only
          </span>
        )}
      </div>

      {g.nextHint && <p className="text-[11px] text-slate-400 dark:text-slate-500">{g.nextHint}</p>}
    </div>
  )
}

// ── Progress header (Task 2) ────────────────────────────────────────────────
// Five high-level stages. Each maps to the granular phase keys the backend
// records in phases_state; stages with no driven phase yet render as pending.

interface HighLevelPhase {
  key: string
  label: string
  icon: React.ElementType
  phases: string[]
}

const HIGH_LEVEL_PHASES: HighLevelPhase[] = [
  { key: 'discovery',      label: 'Discovery',      icon: Compass,     phases: ['ARCHITECTURE_DECISION', 'PLAN_SELECTED'] },
  { key: 'infrastructure', label: 'Infrastructure', icon: Boxes,       phases: ['TERRAFORM_GENERATION', 'TERRAFORM_VALIDATION', 'TERRAFORM_PLAN'] },
  { key: 'delivery',       label: 'Delivery',       icon: Rocket,      phases: ['CICD'] },
  { key: 'governance',     label: 'Governance',     icon: ShieldCheck, phases: ['VALIDATION'] },
  { key: 'deployment',     label: 'Deployment',     icon: Server,      phases: ['KUBERNETES'] },
]

type GroupIntrinsic = 'completed' | 'failed' | 'running' | 'partial' | 'pending'
type GroupRenderStatus = 'completed' | 'failed' | 'running' | 'current' | 'pending'

function groupIntrinsic(s: GuidancePhasesState, phases: string[]): GroupIntrinsic {
  if (phases.length === 0) return 'pending'
  const st = phases.map((p) => statusOf(s, p))
  if (st.some((x) => x === 'failed')) return 'failed'
  if (st.some((x) => x === 'running')) return 'running'
  if (st.every((x) => x === 'completed')) return 'completed'
  if (st.some((x) => x === 'completed' || x === 'awaiting_input')) return 'partial'
  return 'pending'
}

export function WorkflowProgressHeader({
  phasesState,
  className,
}: {
  phasesState: GuidancePhasesState
  className?: string
}) {
  const intrinsic = HIGH_LEVEL_PHASES.map((g) => groupIntrinsic(phasesState, g.phases))
  // The "current" stage is the first that isn't fully completed.
  const currentIdx = intrinsic.findIndex((s) => s !== 'completed')

  return (
    <div className={cn('flex items-center gap-1 overflow-x-auto', className)}>
      {HIGH_LEVEL_PHASES.map((group, i) => {
        const intr = intrinsic[i]
        const status: GroupRenderStatus =
          intr === 'completed'
            ? 'completed'
            : intr === 'failed'
              ? 'failed'
              : intr === 'running'
                ? 'running'
                : i === currentIdx
                  ? 'current'
                  : 'pending'
        return (
          <div key={group.key} className="flex items-center shrink-0">
            <ProgressStep group={group} index={i} status={status} />
            {i < HIGH_LEVEL_PHASES.length - 1 && (
              <div
                className={cn(
                  'w-5 sm:w-8 h-0.5 rounded-full mx-0.5 shrink-0',
                  status === 'completed'
                    ? 'bg-emerald-300 dark:bg-emerald-600/50'
                    : 'bg-slate-200 dark:bg-surface-700',
                )}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

function ProgressStep({
  group,
  index,
  status,
}: {
  group: HighLevelPhase
  index: number
  status: GroupRenderStatus
}) {
  const Icon = group.icon
  return (
    <div className="flex items-center gap-2 shrink-0">
      <div
        className={cn(
          'w-7 h-7 rounded-full flex items-center justify-center shrink-0 border',
          status === 'completed' && 'bg-emerald-500 border-emerald-500 text-white',
          status === 'failed' && 'bg-red-500 border-red-500 text-white',
          status === 'running' && 'bg-brand-600 border-brand-600 text-white',
          status === 'current' && 'bg-brand-50 dark:bg-brand-600/15 border-brand-300 dark:border-brand-500/40 text-brand-600 dark:text-brand-300',
          status === 'pending' && 'bg-slate-100 dark:bg-surface-800 border-slate-200 dark:border-white/[0.06] text-slate-400 dark:text-slate-600',
        )}
      >
        {status === 'completed' ? (
          <CheckCircle2 className="w-4 h-4" />
        ) : status === 'failed' ? (
          <XCircle className="w-4 h-4" />
        ) : status === 'running' ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Icon className="w-3.5 h-3.5" />
        )}
      </div>
      <div className="hidden sm:flex flex-col leading-tight pr-1">
        <span
          className={cn(
            'text-xs font-medium',
            status === 'pending'
              ? 'text-slate-400 dark:text-slate-600'
              : status === 'failed'
                ? 'text-red-600 dark:text-red-300'
                : status === 'completed'
                  ? 'text-slate-700 dark:text-slate-200'
                  : 'text-brand-700 dark:text-brand-300',
          )}
        >
          {group.label}
        </span>
        <span className="text-[10px] text-slate-400 dark:text-slate-600 capitalize">
          {status === 'current' ? 'in progress' : status}
        </span>
      </div>
    </div>
  )
}
