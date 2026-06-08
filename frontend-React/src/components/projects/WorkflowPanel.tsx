import { useEffect, useRef, useState } from 'react'
import {
  Container,
  Boxes,
  ShieldCheck,
  FileSearch,
  ScrollText,
  Play,
  Rocket,
  Loader2,
  Lock,
  CheckCircle2,
  XCircle,
  Clock,
  Circle,
  ArrowDown,
  Search,
  Layers,
  Network,
  Server,
  Database,
  HardDrive,
  RefreshCcw,
} from 'lucide-react'
import { useProjectRole, useStartWorkflow } from '@/hooks/useProjects'
import { cn, timeAgo } from '@/lib/utils'
import { useWorkflowEngine, type WorkflowEngine } from '@/components/workflow/useWorkflowEngine'
import type { PhaseStatus, PhasesState } from '@/components/workflow/workflowEvents'
import {
  WorkflowProgressHeader,
  WorkflowGuidancePanel,
  PHASE_EXPLANATIONS,
} from '@/components/workflow/WorkflowGuidance'
import { WorkflowTimeline } from '@/components/workflow/WorkflowTimeline'
import { DockerBuildBlockedPanel } from '@/components/workflow/DockerBuildBlockedPanel'
import type {
  ArtifactResponse,
  PhaseName,
  ProjectRole,
  WorkflowResponse,
} from '@/types/project'

const CONTRIBUTOR_ROLES = new Set<ProjectRole>([
  'DEVELOPER',
  'CLOUD_ARCHITECT',
  'OWNER',
  'ADMIN',
])

// Optional, non-guided phases. Docker + the guided Terraform flow are first-class
// elsewhere; these remain available (collapsed) without cluttering the main flow.
const LEGACY_PHASE_BUTTONS: { phase: PhaseName; label: string; icon: React.ElementType }[] = [
  { phase: 'KUBERNETES', label: 'Kubernetes', icon: Boxes },
  { phase: 'CICD',       label: 'CI/CD',      icon: ShieldCheck },
]

// ── Phase grouping ────────────────────────────────────────────────────────────
interface GroupPhase {
  key: string
  label: string
  icon: React.ElementType
}
interface PhaseGroup {
  key: string
  label: string
  phases: GroupPhase[]
}

const PHASE_GROUPS: PhaseGroup[] = [
  {
    key: 'discovery',
    label: 'Discovery',
    phases: [
      { key: 'ARCHITECTURE_DECISION', label: 'Analysis',              icon: Search },
      { key: 'PLAN_SELECTED',         label: 'Architecture Decision', icon: Layers },
    ],
  },
  {
    key: 'infrastructure',
    label: 'Infrastructure',
    phases: [
      { key: 'TERRAFORM_GENERATION', label: 'Terraform Generation', icon: Boxes },
      { key: 'TERRAFORM_VALIDATION', label: 'Terraform Validation', icon: ShieldCheck },
      { key: 'TERRAFORM_PLAN',       label: 'Terraform Plan',       icon: FileSearch },
    ],
  },
]

// ── Status helpers ─────────────────────────────────────────────────────────────

// Infrastructure Summary — the human-readable plan digest the backend embeds
// into the TERRAFORM_PLAN phase entry after a successful `terraform plan`.
interface SummaryItem {
  type: string
  label: string
  count: number
}
interface SummaryCategory {
  name: string
  items: SummaryItem[]
}
interface InfrastructureSummary {
  total_resources: number
  resource_counts: Record<string, number>
  categories: SummaryCategory[]
}

/** Read a merged phase status off the engine's `phases` object. */
function statusOf(s: PhasesState, key: string): PhaseStatus {
  const v = s[key]?.status
  if (v === 'completed' || v === 'failed' || v === 'running' || v === 'awaiting_input') return v
  return 'not_started'
}

const STATUS_LABEL: Record<PhaseStatus, string> = {
  completed: 'Completed',
  failed: 'Failed',
  running: 'Running',
  awaiting_input: 'Awaiting input',
  not_started: 'Not started',
}

function statusBadgeClass(status: PhaseStatus): string {
  switch (status) {
    case 'completed':
      return 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-500/30'
    case 'failed':
      return 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-300 border-red-200 dark:border-red-500/30'
    case 'running':
      return 'bg-brand-50 dark:bg-brand-600/15 text-brand-700 dark:text-brand-300 border-brand-200 dark:border-brand-500/30'
    case 'awaiting_input':
      return 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-500/30'
    default:
      return 'bg-slate-100 dark:bg-white/[0.04] text-slate-500 dark:text-slate-400 border-slate-200 dark:border-white/[0.06]'
  }
}

function StatusBadge({ status }: { status: PhaseStatus }) {
  return (
    <span className={cn('text-[10px] px-2 py-0.5 rounded-full border', statusBadgeClass(status))}>
      {STATUS_LABEL[status]}
    </span>
  )
}

function StatusDot({ status }: { status: PhaseStatus }) {
  if (status === 'completed') return <CheckCircle2 className="w-4 h-4 text-emerald-500" />
  if (status === 'failed') return <XCircle className="w-4 h-4 text-red-500" />
  if (status === 'running') return <Loader2 className="w-4 h-4 text-brand-500 animate-spin" />
  if (status === 'awaiting_input') return <Clock className="w-4 h-4 text-amber-500" />
  return <Circle className="w-4 h-4 text-slate-300 dark:text-white/20" />
}

// ── Next-action computation ─────────────────────────────────────────────────────

type NextAction =
  | { kind: 'run'; phase: PhaseName; label: string }
  | { kind: 'running'; label: string }
  | { kind: 'done' }

function nextTerraformAction(s: PhasesState): NextAction {
  const gen = statusOf(s, 'TERRAFORM_GENERATION')
  const val = statusOf(s, 'TERRAFORM_VALIDATION')
  const plan = statusOf(s, 'TERRAFORM_PLAN')

  if (gen === 'running') return { kind: 'running', label: 'Generating…' }
  if (val === 'running') return { kind: 'running', label: 'Validating…' }
  if (plan === 'running') return { kind: 'running', label: 'Planning…' }

  if (gen !== 'completed')
    return { kind: 'run', phase: 'TERRAFORM_GENERATION', label: gen === 'failed' ? 'Retry Generation' : 'Run Generation' }
  if (val !== 'completed')
    return { kind: 'run', phase: 'TERRAFORM_VALIDATION', label: val === 'failed' ? 'Retry Validation' : 'Run Validation' }
  if (plan !== 'completed')
    return { kind: 'run', phase: 'TERRAFORM_PLAN', label: plan === 'failed' ? 'Retry Plan' : 'Run Plan' }
  return { kind: 'done' }
}

function formatBuildDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}m ${s}s`
}

// ── Root ───────────────────────────────────────────────────────────────────────

interface Props {
  projectId: string
  workflows: WorkflowResponse[]
  /** Project artifacts — used by the engine-fed WorkflowTimeline counters. */
  artifacts?: ArtifactResponse[]
}

export function WorkflowPanel({ projectId, workflows, artifacts = [] }: Props) {
  const latest = workflows[0]
  const role = useProjectRole(projectId)
  const canRun = !!role && CONTRIBUTOR_ROLES.has(role)
  return (
    <div className="space-y-4">
      {canRun ? <StartWorkflowCard projectId={projectId} /> : <ReadOnlyHint role={role} />}
      {latest && (
        <ActiveWorkflowCard
          projectId={projectId}
          workflow={latest}
          canRun={canRun}
          artifacts={artifacts}
        />
      )}
      {workflows.length > 1 && <WorkflowHistory workflows={workflows.slice(1)} />}
    </div>
  )
}

function ReadOnlyHint({ role }: { role: ProjectRole | null }) {
  return (
    <div className="p-3 rounded-xl border border-slate-200 dark:border-white/[0.06] bg-slate-50 dark:bg-surface-900/40 flex items-center gap-2 text-xs text-slate-500">
      <Lock className="w-3.5 h-3.5" />
      <span>
        {role
          ? `Your role (${role}) is read-only on this project.`
          : 'Read-only access — sign in or request a contributor role.'}
      </span>
    </div>
  )
}

function StartWorkflowCard({ projectId }: { projectId: string }) {
  const [prompt, setPrompt] = useState('')
  const { mutateAsync, isPending, error } = useStartWorkflow(projectId)

  async function onStart() {
    if (!prompt.trim()) return
    await mutateAsync({ prompt: prompt.trim() })
    setPrompt('')
  }

  return (
    <div
      className={cn(
        'p-4 rounded-xl space-y-3',
        'bg-white dark:bg-surface-800/40',
        'border border-slate-200 dark:border-white/[0.06]',
      )}
    >
      <div className="flex items-center gap-2">
        <Rocket className="w-4 h-4 text-brand-600 dark:text-brand-400" />
        <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Start workflow</h3>
      </div>
      <p className="text-xs text-slate-500">
        Runs analysis + planning + cost. Phase actions become available after a plan is selected.
      </p>
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={3}
        placeholder="Describe what you want generated for this project…"
        className={cn(
          'w-full px-3 py-2 rounded-lg text-sm',
          'bg-slate-50 dark:bg-surface-900/40',
          'border border-slate-200 dark:border-white/[0.08]',
          'text-slate-900 dark:text-white',
          'placeholder:text-slate-400 dark:placeholder:text-slate-600',
          'focus:outline-none focus:ring-2 focus:ring-brand-500/40',
        )}
      />
      {error && <div className="text-xs text-red-600 dark:text-red-400">{error.message}</div>}
      <div className="flex justify-end">
        <button
          onClick={onStart}
          disabled={isPending || !prompt.trim()}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium bg-brand-600 hover:bg-brand-500 text-white disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
          Start
        </button>
      </div>
    </div>
  )
}

function ActiveWorkflowCard({
  projectId,
  workflow,
  canRun,
  artifacts,
}: {
  projectId: string
  workflow: WorkflowResponse
  canRun: boolean
  artifacts: ArtifactResponse[]
}) {
  // The single reactive engine instance for this workflow. Everything below is
  // a pure renderer over `engine` — no component opens a socket or calls an API.
  const engine = useWorkflowEngine(projectId, workflow, canRun)
  const phases = engine.phases

  return (
    <div
      className={cn(
        'p-4 rounded-xl space-y-4',
        'bg-white dark:bg-surface-800/40',
        'border border-slate-200 dark:border-white/[0.06]',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Latest workflow</h3>
          <div className="text-[11px] text-slate-500 mt-0.5 font-mono truncate">{workflow.id}</div>
        </div>
        <div className="flex items-center gap-2 shrink-0 text-xs">
          <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-white/[0.04] capitalize">
            {workflow.status}
          </span>
          <span className="text-slate-400">{timeAgo(workflow.created_at)}</span>
        </div>
      </div>

      {/* Read-only timeline, fed by the engine's merged state (single placement). */}
      <WorkflowTimeline
        workflow={{ ...workflow, phases_state: phases } as WorkflowResponse}
        artifacts={artifacts}
      />

      {/* High-level progress header — Discovery → Deployment */}
      <WorkflowProgressHeader phasesState={phases} />

      {/* Guidance: where you are, what happened, what to do next */}
      <WorkflowGuidancePanel
        phasesState={phases}
        canRun={canRun}
        onRunPhase={(phase) => engine.runPhase(phase as PhaseName)}
        isRunning={engine.runPhasePending}
      />

      {/* Grouped phase overview */}
      {PHASE_GROUPS.map((group) => (
        <PhaseGroupCard key={group.key} group={group} engine={engine} />
      ))}

      {/* Docker: generation → review → build → live logs → completion */}
      <DockerSection engine={engine} />

      {engine.runPhaseError && (
        <div className="text-xs text-red-600 dark:text-red-400">{engine.runPhaseError.message}</div>
      )}

      {/* Optional, non-guided phases — collapsed so they don't clutter the flow */}
      <OtherPhases engine={engine} />
    </div>
  )
}

// ── Grouped phase card ──────────────────────────────────────────────────────────

function PhaseGroupCard({ group, engine }: { group: PhaseGroup; engine: WorkflowEngine }) {
  const phases = engine.phases
  const isInfra = group.key === 'infrastructure'
  const planSummary =
    statusOf(phases, 'TERRAFORM_PLAN') === 'completed'
      ? (phases['TERRAFORM_PLAN']?.infrastructure_summary as InfrastructureSummary | undefined)
      : undefined
  return (
    <div className="rounded-lg border border-slate-200 dark:border-white/[0.06] overflow-hidden">
      <div className="px-3 py-2 bg-slate-50 dark:bg-surface-900/40 border-b border-slate-100 dark:border-white/[0.04]">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          {group.label}
        </span>
      </div>

      {/* Vertical stepper */}
      <ol className="p-3 space-y-0">
        {group.phases.map((phase, idx) => {
          const status = statusOf(phases, phase.key)
          const entry = phases[phase.key]
          const updatedAt = entry?.updated_at as string | undefined
          const Icon = phase.icon
          return (
            <li key={phase.key}>
              <div className="flex items-center gap-3 py-1.5">
                <StatusDot status={status} />
                <Icon className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                <div className="flex-1 min-w-0">
                  <span className="block text-sm font-medium text-slate-800 dark:text-slate-200 truncate">
                    {phase.label}
                  </span>
                  {PHASE_EXPLANATIONS[phase.key] && (
                    <span className="block text-[11px] text-slate-400 dark:text-slate-500 leading-snug">
                      {PHASE_EXPLANATIONS[phase.key]}
                    </span>
                  )}
                </div>
                {updatedAt && status !== 'not_started' && (
                  <span className="text-[10px] text-slate-400 hidden sm:inline shrink-0">
                    {timeAgo(updatedAt)}
                  </span>
                )}
                <StatusBadge status={status} />
              </div>
              {idx < group.phases.length - 1 && (
                <div className="flex justify-start pl-[7px]">
                  <ArrowDown className="w-3 h-3 text-slate-300 dark:text-white/20" />
                </div>
              )}
            </li>
          )
        })}
      </ol>

      {/* Infrastructure: single next action + live logs + summary */}
      {isInfra && (
        <div className="px-3 pb-3 space-y-3 border-t border-slate-100 dark:border-white/[0.04] pt-3">
          <InfrastructureAction engine={engine} />
          <TerraformLogViewer engine={engine} />
          {planSummary && <InfrastructureSummaryCard summary={planSummary} />}
        </div>
      )}
    </div>
  )
}

// ── Phase-driven action ─────────────────────────────────────────────────────────

function InfrastructureAction({ engine }: { engine: WorkflowEngine }) {
  const phases = engine.phases
  const action = nextTerraformAction(phases)
  const planReady = statusOf(phases, 'PLAN_SELECTED') === 'completed'

  if (action.kind === 'done') {
    return (
      <div className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20 text-emerald-700 dark:text-emerald-300">
        <CheckCircle2 className="w-4 h-4" />
        Plan Completed
      </div>
    )
  }

  if (action.kind === 'running') {
    return (
      <div className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-brand-50 dark:bg-brand-600/15 border border-brand-200 dark:border-brand-500/20 text-brand-700 dark:text-brand-300">
        <Loader2 className="w-4 h-4 animate-spin" />
        {action.label}
      </div>
    )
  }

  // kind === 'run'
  const needsPlan = action.phase === 'TERRAFORM_GENERATION' && !planReady
  const disabled = engine.runPhasePending || !engine.canRun || needsPlan
  const title = !engine.canRun
    ? 'Read-only role'
    : needsPlan
      ? 'Select a plan in the Architecture tab first'
      : undefined

  return (
    <div className="space-y-1">
      <button
        onClick={() => engine.runPhase(action.phase)}
        disabled={disabled}
        title={title}
        className={cn(
          'inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
          'bg-brand-600 hover:bg-brand-500 text-white',
          'disabled:opacity-50 disabled:cursor-not-allowed',
        )}
      >
        {engine.runPhasePending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
        {action.label}
      </button>
      {needsPlan && (
        <p className="text-[11px] text-slate-500">Select a plan in the Architecture tab to begin.</p>
      )}
    </div>
  )
}

// ── Terraform live log viewer (pure renderer) ───────────────────────────────────

function TerraformLogViewer({ engine }: { engine: WorkflowEngine }) {
  const validateStatus = engine.statusOf('TERRAFORM_VALIDATION')
  const planStatus = engine.statusOf('TERRAFORM_PLAN')
  const active = engine.terraformActive

  // The phase shown in the header (sticky after completion so the result is
  // still readable once the stream closes).
  const displayPhaseKey: 'TERRAFORM_VALIDATION' | 'TERRAFORM_PLAN' | null =
    active === 'terraform_validate'
      ? 'TERRAFORM_VALIDATION'
      : active === 'terraform_plan'
        ? 'TERRAFORM_PLAN'
        : planStatus !== 'not_started'
          ? 'TERRAFORM_PLAN'
          : validateStatus !== 'not_started'
            ? 'TERRAFORM_VALIDATION'
            : null

  const displayStatus = displayPhaseKey ? engine.statusOf(displayPhaseKey) : 'not_started'
  const displayUpdatedAt = displayPhaseKey
    ? (engine.phases[displayPhaseKey]?.updated_at as string | undefined)
    : undefined
  const lines = displayPhaseKey ? engine.logsOf(displayPhaseKey) : []

  const scrollRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [lines])

  // Nothing to show until a terraform phase has at least been attempted.
  if (!displayPhaseKey && lines.length === 0) return null

  const title =
    displayPhaseKey === 'TERRAFORM_VALIDATION'
      ? 'Terraform Validation'
      : displayPhaseKey === 'TERRAFORM_PLAN'
        ? 'Terraform Plan'
        : 'Terraform logs'

  return (
    <div className="rounded-lg border border-slate-200 dark:border-white/[0.06] overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-50 dark:bg-surface-900/40 border-b border-slate-100 dark:border-white/[0.04]">
        <span className="text-[11px] font-medium text-slate-600 dark:text-slate-300 inline-flex items-center gap-1.5">
          <ScrollText className="w-3 h-3" />
          {title}
          {active && <span className="text-brand-500">· live</span>}
        </span>
        <div className="flex items-center gap-2">
          {displayUpdatedAt && displayStatus !== 'running' && (
            <span className="text-[10px] text-slate-400">{timeAgo(displayUpdatedAt)}</span>
          )}
          {displayStatus === 'completed' && (
            <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
              <CheckCircle2 className="w-3 h-3" /> Success
            </span>
          )}
          {displayStatus === 'failed' && (
            <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-300">
              <XCircle className="w-3 h-3" /> Failed
            </span>
          )}
          {displayStatus === 'running' && (
            <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-brand-50 dark:bg-brand-600/15 text-brand-700 dark:text-brand-300">
              <Loader2 className="w-3 h-3 animate-spin" /> Running
            </span>
          )}
        </div>
      </div>
      <div
        ref={scrollRef}
        className="max-h-48 overflow-auto bg-slate-950 text-slate-200 font-mono text-[11px] leading-relaxed p-3"
      >
        {lines.length === 0 ? (
          <span className="text-slate-500">
            {active ? 'Waiting for terraform output…' : 'No live output for this run.'}
          </span>
        ) : (
          lines.map((l, i) => (
            <div key={i} className="whitespace-pre-wrap break-all">
              {l}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

// ── Infrastructure Summary ──────────────────────────────────────────────────────

const CATEGORY_ICON: Record<string, React.ElementType> = {
  Networking: Network,
  Compute: Server,
  Database: Database,
  Storage: HardDrive,
  Security: ShieldCheck,
  Other: Boxes,
}

/** Minimal English pluralizer — enough for AWS resource labels. */
function pluralize(label: string, count: number): string {
  if (count === 1) return label
  if (/[^aeiou]y$/i.test(label)) return label.replace(/y$/i, 'ies')
  if (/(s|x|z|ch|sh)$/i.test(label)) return `${label}es`
  return `${label}s`
}

function InfrastructureSummaryCard({ summary }: { summary: InfrastructureSummary }) {
  const categories = summary.categories ?? []

  return (
    <div className="rounded-lg border border-emerald-200 dark:border-emerald-500/20 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 bg-emerald-50 dark:bg-emerald-500/10 border-b border-emerald-100 dark:border-emerald-500/20">
        <span className="text-xs font-semibold text-emerald-800 dark:text-emerald-200 inline-flex items-center gap-1.5">
          <Boxes className="w-3.5 h-3.5" />
          Infrastructure Summary
        </span>
        <span className="text-[10px] text-emerald-700 dark:text-emerald-300">
          {summary.total_resources} resource{summary.total_resources === 1 ? '' : 's'}
        </span>
      </div>

      <p className="px-3 pt-2 text-[11px] text-slate-500 dark:text-slate-400">
        {PHASE_EXPLANATIONS.INFRASTRUCTURE_SUMMARY}
      </p>

      {categories.length === 0 ? (
        <div className="p-3 text-xs text-slate-500">The plan creates no resources.</div>
      ) : (
        <div className="p-3 grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3">
          {categories.map((cat) => {
            const Icon = CATEGORY_ICON[cat.name] ?? Boxes
            return (
              <div key={cat.name} className="space-y-1.5">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  <Icon className="w-3.5 h-3.5" />
                  {cat.name}
                </div>
                <ul className="space-y-1 pl-0.5">
                  {cat.items.map((item) => (
                    <li
                      key={item.type}
                      className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                      <span>
                        <span className="font-medium">{item.count}</span>{' '}
                        {pluralize(item.label, item.count)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Docker: generation → approval → build → logs → completion ────────────────────
// First-class, fully engine-driven. Replaces both the legacy "Run Docker" button
// and the standalone build section so there is one Docker surface.

function DockerSection({ engine }: { engine: WorkflowEngine }) {
  const genStatus = engine.statusOf('DOCKER')
  const planReady = engine.statusOf('PLAN_SELECTED') === 'completed'
  const generated = genStatus === 'completed'
  const build = engine.build

  const scrollRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [build.logs])

  const buildLabel =
    build.status === 'failed' ? 'Retry Build' : build.status === 'completed' ? 'Rebuild Image' : 'Build Docker Image'
  const buildDisabled = !engine.canRun || build.starting || build.status === 'running'
  const genDisabled = !engine.canRun || engine.runPhasePending || !planReady || genStatus === 'running'
  const genLabel = genStatus === 'failed' ? 'Retry Docker Generation' : 'Generate Docker Artifacts'

  return (
    <div className="rounded-lg border border-slate-200 dark:border-white/[0.06] overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 bg-slate-50 dark:bg-surface-900/40 border-b border-slate-100 dark:border-white/[0.04]">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 inline-flex items-center gap-1.5">
          <Container className="w-3.5 h-3.5" />
          Docker
        </span>
        <StatusBadge status={generated ? build.status : genStatus} />
      </div>

      <div className="p-3 space-y-3">
        {!generated ? (
          // ── Step 1: generation ────────────────────────────────────────────
          <>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              {PHASE_EXPLANATIONS.DOCKER}
            </p>
            <div className="space-y-1">
              <button
                onClick={() => engine.runPhase('DOCKER')}
                disabled={genDisabled}
                title={!engine.canRun ? 'Read-only role' : !planReady ? 'Select a plan first' : undefined}
                className={cn(
                  'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                  'bg-brand-600 hover:bg-brand-500 text-white',
                  'disabled:opacity-50 disabled:cursor-not-allowed',
                )}
              >
                {genStatus === 'running' ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4" />
                )}
                {genStatus === 'running' ? 'Generating…' : genLabel}
              </button>
              {!planReady && (
                <p className="text-[11px] text-slate-500">
                  Select a plan in the Architecture tab to begin.
                </p>
              )}
            </div>
          </>
        ) : (
          // ── Step 2: review + build ────────────────────────────────────────
          <>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              Docker artifacts generated. Review them in the Docker tab, then build the image with the
              existing build engine. Logs stream live below.
            </p>

            <div className="flex items-center gap-3 flex-wrap">
              {build.status !== 'running' ? (
                <button
                  onClick={() => engine.startBuild()}
                  disabled={buildDisabled}
                  title={!engine.canRun ? 'Read-only role' : undefined}
                  className={cn(
                    'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                    'bg-brand-600 hover:bg-brand-500 text-white',
                    'disabled:opacity-50 disabled:cursor-not-allowed',
                  )}
                >
                  {build.starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                  {buildLabel}
                </button>
              ) : (
                <span className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-brand-50 dark:bg-brand-600/15 border border-brand-200 dark:border-brand-500/20 text-brand-700 dark:text-brand-300">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Building image…
                </span>
              )}

              {build.status === 'completed' && (
                <span className="inline-flex items-center gap-1 text-xs text-slate-500">
                  <Clock className="w-3.5 h-3.5" />
                  {build.durationSeconds != null
                    ? `Completed in ${formatBuildDuration(build.durationSeconds)}`
                    : 'Completed'}
                  {build.finishedAt && <span className="text-slate-400">· {timeAgo(build.finishedAt)}</span>}
                </span>
              )}
              {build.status === 'failed' && build.finishedAt && (
                <span className="inline-flex items-center gap-1 text-xs text-red-500">
                  <XCircle className="w-3.5 h-3.5" /> Failed · {timeAgo(build.finishedAt)}
                </span>
              )}
            </div>

            {/* Build blocked by the PrebuildGate (HTTP 422). The build never
                started and no WS was opened — show WHY, with a Fix & Retry CTA. */}
            {build.blocked && (
              <DockerBuildBlockedPanel
                blocked={build.blocked}
                onRetry={() => engine.regenerateDocker()}
                retrying={engine.runPhasePending}
                canRun={engine.canRun}
              />
            )}

            {build.imageTag && (
              <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400 break-all">
                image: {build.imageTag}
              </div>
            )}

            {build.status === 'failed' && build.failureReason && (
              <div className="text-xs text-red-600 dark:text-red-400 break-all">{build.failureReason}</div>
            )}

            {/* Build-trigger error (e.g. the 409 phase-cursor gate). Offer the
                recovery that resets the backing task to docker_completed. */}
            {build.error && (
              <div className="space-y-1.5">
                <div className="text-xs text-red-600 dark:text-red-400 break-all">{build.error}</div>
                <button
                  onClick={() => engine.regenerateDocker()}
                  disabled={!engine.canRun || engine.runPhasePending}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-200 dark:border-white/[0.08] bg-white dark:bg-surface-900/40 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-white/[0.04] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <RefreshCcw className={cn('w-3.5 h-3.5', engine.runPhasePending && 'animate-spin')} />
                  Re-generate Docker artifacts
                </button>
              </div>
            )}

            {/* Live logs — same UX as the Terraform log viewer. */}
            {(build.logs.length > 0 || build.status === 'running') && (
              <div className="rounded-lg border border-slate-200 dark:border-white/[0.06] overflow-hidden">
                <div className="flex items-center justify-between px-3 py-1.5 bg-slate-50 dark:bg-surface-900/40 border-b border-slate-100 dark:border-white/[0.04]">
                  <span className="text-[11px] font-medium text-slate-600 dark:text-slate-300 inline-flex items-center gap-1.5">
                    <ScrollText className="w-3 h-3" />
                    Build logs
                    {build.live && <span className="text-brand-500">· live</span>}
                  </span>
                </div>
                <div
                  ref={scrollRef}
                  className="max-h-48 overflow-auto bg-slate-950 text-slate-200 font-mono text-[11px] leading-relaxed p-3"
                >
                  {build.logs.length === 0 ? (
                    <span className="text-slate-500">Waiting for build output…</span>
                  ) : (
                    build.logs.map((l, i) => (
                      <div key={i} className="whitespace-pre-wrap break-all">
                        {l}
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── Other (optional) phases ─────────────────────────────────────────────────────

function OtherPhases({ engine }: { engine: WorkflowEngine }) {
  const phases = engine.phases
  return (
    <details className="rounded-lg border border-slate-200 dark:border-white/[0.06]">
      <summary className="px-3 py-2 text-xs font-semibold text-slate-600 dark:text-slate-300 cursor-pointer select-none">
        Other phases (Kubernetes · CI/CD)
      </summary>
      <div className="p-3 grid grid-cols-2 gap-2">
        {LEGACY_PHASE_BUTTONS.map(({ phase, label, icon: Icon }) => {
          const status = statusOf(phases, phase)
          return (
            <button
              key={phase}
              onClick={() => engine.runPhase(phase)}
              disabled={engine.runPhasePending || status === 'running' || !engine.canRun}
              title={!engine.canRun ? 'Read-only role' : undefined}
              className={cn(
                'inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-colors border',
                'disabled:opacity-50 disabled:cursor-not-allowed',
                status === 'completed'
                  ? 'bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/20 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-500/15'
                  : status === 'failed'
                    ? 'bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/20 text-red-700 dark:text-red-300 hover:bg-red-100 dark:hover:bg-red-500/15'
                    : 'bg-white dark:bg-surface-900/40 border-slate-200 dark:border-white/[0.08] text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-white/[0.04]',
              )}
            >
              {engine.runPhasePending && engine.runPhaseVariable === phase ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Icon className="w-3.5 h-3.5" />
              )}
              {status === 'completed' ? `Re-run ${label}` : `Run ${label}`}
            </button>
          )
        })}
      </div>
    </details>
  )
}

function WorkflowHistory({ workflows }: { workflows: WorkflowResponse[] }) {
  return (
    <details
      className={cn(
        'p-4 rounded-xl',
        'bg-white dark:bg-surface-800/40',
        'border border-slate-200 dark:border-white/[0.06]',
      )}
    >
      <summary className="text-sm font-semibold text-slate-700 dark:text-slate-300 cursor-pointer">
        Previous workflows ({workflows.length})
      </summary>
      <ul className="mt-3 space-y-1">
        {workflows.map((w) => (
          <li
            key={w.id}
            className="flex items-center justify-between text-xs py-1.5 border-b last:border-0 border-slate-100 dark:border-white/[0.04]"
          >
            <span className="font-mono text-slate-500 truncate">{w.id.slice(0, 8)}…</span>
            <span className="capitalize text-slate-500">{w.status}</span>
            <span className="text-slate-400">{timeAgo(w.created_at)}</span>
          </li>
        ))}
      </ul>
    </details>
  )
}
