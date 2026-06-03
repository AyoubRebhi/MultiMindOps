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
} from 'lucide-react'
import {
  useProjectRole,
  useRunPhase,
  useStartWorkflow,
  useRefreshProjectWorkflows,
} from '@/hooks/useProjects'
import { cn, timeAgo } from '@/lib/utils'
import { getWsTerraformUrl, type TerraformWsPhase } from '@/services/workflowApi'
import { tokenStorage } from '@/lib/tokenStorage'
import type { PhaseName, ProjectRole, WorkflowResponse } from '@/types/project'

const CONTRIBUTOR_ROLES = new Set<ProjectRole>([
  'DEVELOPER',
  'CLOUD_ARCHITECT',
  'OWNER',
  'ADMIN',
])

// Legacy / parallel phases — kept available under "Other phases" so they don't
// clutter the guided Discovery → Infrastructure flow.
const LEGACY_PHASE_BUTTONS: { phase: PhaseName; label: string; icon: React.ElementType }[] = [
  { phase: 'DOCKER',     label: 'Docker',        icon: Container },
  { phase: 'TERRAFORM',  label: 'Terraform (AI)', icon: Boxes },
  { phase: 'KUBERNETES', label: 'Kubernetes',    icon: Boxes },
  { phase: 'CICD',       label: 'CI/CD',         icon: ShieldCheck },
]

// ── Phase grouping (Task 4) ───────────────────────────────────────────────────
// Extensible group model. Group 3 (Delivery) and Group 4 (Governance) are
// intentionally left out — the structure supports adding them later without a
// rewrite.
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
  // Group 3 — Delivery     → CI/CD              (future)
  // Group 4 — Governance   → Security, Cost     (future)
]

const TF_WS_PHASE: Partial<Record<string, TerraformWsPhase>> = {
  TERRAFORM_VALIDATION: 'terraform_validate',
  TERRAFORM_PLAN: 'terraform_plan',
}

// ── Status helpers ─────────────────────────────────────────────────────────────

type PhaseStatus = 'completed' | 'failed' | 'running' | 'awaiting_input' | 'not_started'

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

interface PhaseEntry {
  status?: string
  updated_at?: string
  task_id?: string
  error?: string
  infrastructure_summary?: InfrastructureSummary
}
type PhasesState = Record<string, PhaseEntry>

function statusOf(s: PhasesState, key: string): PhaseStatus {
  const v = s[key]?.status
  if (v === 'completed' || v === 'failed' || v === 'running' || v === 'awaiting_input') return v
  return 'not_started'
}

/** The backing task id is stamped into phases_state by start_workflow. */
function backingTaskId(s: PhasesState): string | null {
  return s['ARCHITECTURE_DECISION']?.task_id ?? null
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

// ── Next-action computation (Task 3) ───────────────────────────────────────────

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

// ── Root ───────────────────────────────────────────────────────────────────────

interface Props {
  projectId: string
  workflows: WorkflowResponse[]
}

export function WorkflowPanel({ projectId, workflows }: Props) {
  const latest = workflows[0]
  const role = useProjectRole(projectId)
  const canRun = !!role && CONTRIBUTOR_ROLES.has(role)
  return (
    <div className="space-y-4">
      {canRun ? <StartWorkflowCard projectId={projectId} /> : <ReadOnlyHint role={role} />}
      {latest && <ActiveWorkflowCard projectId={projectId} workflow={latest} canRun={canRun} />}
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
}: {
  projectId: string
  workflow: WorkflowResponse
  canRun: boolean
}) {
  const runPhase = useRunPhase(projectId, workflow.id)
  const phasesState = (workflow.phases_state ?? {}) as PhasesState

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

      {/* Grouped phase overview (Task 2 + Task 4) */}
      {PHASE_GROUPS.map((group) => (
        <PhaseGroupCard
          key={group.key}
          group={group}
          phasesState={phasesState}
          projectId={projectId}
          runPhase={runPhase}
          canRun={canRun}
        />
      ))}

      {runPhase.error && (
        <div className="text-xs text-red-600 dark:text-red-400">{runPhase.error.message}</div>
      )}

      {/* Legacy / parallel phases — tucked away so they don't clutter the flow */}
      <OtherPhases phasesState={phasesState} runPhase={runPhase} canRun={canRun} />
    </div>
  )
}

// ── Grouped phase card ──────────────────────────────────────────────────────────

function PhaseGroupCard({
  group,
  phasesState,
  projectId,
  runPhase,
  canRun,
}: {
  group: PhaseGroup
  phasesState: PhasesState
  projectId: string
  runPhase: ReturnType<typeof useRunPhase>
  canRun: boolean
}) {
  const isInfra = group.key === 'infrastructure'
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
          const status = statusOf(phasesState, phase.key)
          const entry = phasesState[phase.key]
          const Icon = phase.icon
          return (
            <li key={phase.key}>
              <div className="flex items-center gap-3 py-1.5">
                <StatusDot status={status} />
                <Icon className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                <span className="text-sm font-medium text-slate-800 dark:text-slate-200 flex-1 min-w-0 truncate">
                  {phase.label}
                </span>
                {entry?.updated_at && status !== 'not_started' && (
                  <span className="text-[10px] text-slate-400 hidden sm:inline">
                    {timeAgo(entry.updated_at)}
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

      {/* Infrastructure: single next action + live logs (Task 3 + Task 5) */}
      {isInfra && (
        <div className="px-3 pb-3 space-y-3 border-t border-slate-100 dark:border-white/[0.04] pt-3">
          <InfrastructureAction phasesState={phasesState} runPhase={runPhase} canRun={canRun} />
          <TerraformLogViewer projectId={projectId} phasesState={phasesState} />
          {statusOf(phasesState, 'TERRAFORM_PLAN') === 'completed' &&
            phasesState['TERRAFORM_PLAN']?.infrastructure_summary && (
              <InfrastructureSummaryCard
                summary={phasesState['TERRAFORM_PLAN'].infrastructure_summary}
              />
            )}
        </div>
      )}
    </div>
  )
}

// ── Phase-driven action (Task 3) ────────────────────────────────────────────────

function InfrastructureAction({
  phasesState,
  runPhase,
  canRun,
}: {
  phasesState: PhasesState
  runPhase: ReturnType<typeof useRunPhase>
  canRun: boolean
}) {
  const action = nextTerraformAction(phasesState)
  const planReady = statusOf(phasesState, 'PLAN_SELECTED') === 'completed'

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
  const disabled = runPhase.isPending || !canRun || needsPlan
  const title = !canRun
    ? 'Read-only role'
    : needsPlan
      ? 'Select a plan in the Architecture tab first'
      : undefined

  return (
    <div className="space-y-1">
      <button
        onClick={() => runPhase.mutate(action.phase)}
        disabled={disabled}
        title={title}
        className={cn(
          'inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
          'bg-brand-600 hover:bg-brand-500 text-white',
          'disabled:opacity-50 disabled:cursor-not-allowed',
        )}
      >
        {runPhase.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
        {action.label}
      </button>
      {needsPlan && (
        <p className="text-[11px] text-slate-500">Select a plan in the Architecture tab to begin.</p>
      )}
    </div>
  )
}

// ── Terraform live log viewer (Task 1 + Task 5) ─────────────────────────────────

function TerraformLogViewer({
  projectId,
  phasesState,
}: {
  projectId: string
  phasesState: PhasesState
}) {
  const taskId = backingTaskId(phasesState)
  const refresh = useRefreshProjectWorkflows(projectId)

  const validateStatus = statusOf(phasesState, 'TERRAFORM_VALIDATION')
  const planStatus = statusOf(phasesState, 'TERRAFORM_PLAN')

  // Stream whichever phase is running; otherwise reflect the most recent one.
  const active: TerraformWsPhase | null =
    validateStatus === 'running'
      ? 'terraform_validate'
      : planStatus === 'running'
        ? 'terraform_plan'
        : null

  // The phase shown in the header (sticky after completion so the result is
  // still readable once the stream closes).
  const displayPhaseKey =
    active === 'terraform_validate'
      ? 'TERRAFORM_VALIDATION'
      : active === 'terraform_plan'
        ? 'TERRAFORM_PLAN'
        : planStatus !== 'not_started'
          ? 'TERRAFORM_PLAN'
          : validateStatus !== 'not_started'
            ? 'TERRAFORM_VALIDATION'
            : null

  const displayStatus = displayPhaseKey ? statusOf(phasesState, displayPhaseKey) : 'not_started'
  const displayUpdatedAt = displayPhaseKey ? phasesState[displayPhaseKey]?.updated_at : undefined

  const [lines, setLines] = useState<string[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  // Always invalidate with the latest callback when a stream settles (Task 1).
  const refreshRef = useRef(refresh)
  refreshRef.current = refresh

  useEffect(() => {
    if (!taskId || !active) return
    setLines([])
    const url = getWsTerraformUrl(taskId, active, tokenStorage.getAccess())
    const ws = new WebSocket(url)
    wsRef.current = ws
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
    }, 30_000)

    ws.onmessage = (evt) => {
      let msg: { type?: string; message?: string; status?: string }
      try {
        msg = JSON.parse(evt.data as string)
      } catch {
        return
      }
      if (msg.type === 'pong' || msg.type === 'info') return
      if (msg.type === 'complete') {
        // Async phase finished → refresh workflow so the timeline flips
        // Running → Completed/Failed without a manual refresh or polling.
        refreshRef.current()
        return
      }
      if (msg.type === 'error') {
        setLines((prev) => [...prev, `ERROR: ${msg.message ?? 'unknown'}`])
        refreshRef.current()
        return
      }
      if (msg.message != null) setLines((prev) => [...prev, msg.message as string])
    }
    ws.onclose = () => clearInterval(ping)

    return () => {
      clearInterval(ping)
      try {
        ws.close()
      } catch {
        /* noop */
      }
      wsRef.current = null
    }
  }, [taskId, active])

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

// ── Infrastructure Summary (Phase 4) ────────────────────────────────────────────
//
// Reads the categorized summary the backend embeds into the TERRAFORM_PLAN
// phase entry and renders it as a readable "what will be created" card. Shown
// only when Terraform Plan succeeded (gated by the caller).

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

      {categories.length === 0 ? (
        <div className="p-3 text-xs text-slate-500">
          The plan creates no resources.
        </div>
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

// ── Other (legacy) phases ───────────────────────────────────────────────────────

function OtherPhases({
  phasesState,
  runPhase,
  canRun,
}: {
  phasesState: PhasesState
  runPhase: ReturnType<typeof useRunPhase>
  canRun: boolean
}) {
  return (
    <details className="rounded-lg border border-slate-200 dark:border-white/[0.06]">
      <summary className="px-3 py-2 text-xs font-semibold text-slate-600 dark:text-slate-300 cursor-pointer select-none">
        Other phases (Docker · Kubernetes · CI/CD)
      </summary>
      <div className="p-3 grid grid-cols-2 lg:grid-cols-4 gap-2">
        {LEGACY_PHASE_BUTTONS.map(({ phase, label, icon: Icon }) => {
          const status = statusOf(phasesState, phase)
          return (
            <button
              key={phase}
              onClick={() => runPhase.mutate(phase)}
              disabled={runPhase.isPending || status === 'running' || !canRun}
              title={!canRun ? 'Read-only role' : undefined}
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
              {runPhase.isPending && runPhase.variables === phase ? (
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
