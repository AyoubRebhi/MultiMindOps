import { useState } from 'react'
import { Container, Boxes, ShieldCheck, Play, Rocket, Loader2, Lock } from 'lucide-react'
import { useProjectRole, useRunPhase, useStartWorkflow } from '@/hooks/useProjects'
import { cn, timeAgo } from '@/lib/utils'
import type { PhaseName, ProjectRole, WorkflowResponse } from '@/types/project'

const CONTRIBUTOR_ROLES = new Set<ProjectRole>([
  'DEVELOPER',
  'CLOUD_ARCHITECT',
  'OWNER',
  'ADMIN',
])

const PHASE_BUTTONS: { phase: PhaseName; label: string; icon: React.ElementType }[] = [
  { phase: 'DOCKER',     label: 'Run Docker',     icon: Container },
  { phase: 'TERRAFORM',  label: 'Run Terraform',  icon: Boxes },
  { phase: 'KUBERNETES', label: 'Run Kubernetes', icon: Boxes },
  { phase: 'CICD',       label: 'Run CI/CD',      icon: ShieldCheck },
]

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
      {canRun ? (
        <StartWorkflowCard projectId={projectId} />
      ) : (
        <ReadOnlyHint role={role} />
      )}
      {latest && (
        <ActiveWorkflowCard projectId={projectId} workflow={latest} canRun={canRun} />
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
      {error && (
        <div className="text-xs text-red-600 dark:text-red-400">{error.message}</div>
      )}
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
  const phasesState = (workflow.phases_state ?? {}) as Record<string, { status?: string }>

  return (
    <div
      className={cn(
        'p-4 rounded-xl space-y-3',
        'bg-white dark:bg-surface-800/40',
        'border border-slate-200 dark:border-white/[0.06]',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
            Latest workflow
          </h3>
          <div className="text-[11px] text-slate-500 mt-0.5 font-mono truncate">
            {workflow.id}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0 text-xs">
          <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-white/[0.04] capitalize">
            {workflow.status}
          </span>
          <span className="text-slate-400">{timeAgo(workflow.created_at)}</span>
        </div>
      </div>

      <Timeline phasesState={phasesState} currentPhase={workflow.current_phase ?? ''} />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        {PHASE_BUTTONS.map(({ phase, label, icon: Icon }) => {
          const status = phasesState[phase]?.status
          return (
            <button
              key={phase}
              onClick={() => runPhase.mutate(phase)}
              disabled={runPhase.isPending || !canRun}
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
              {status === 'completed' ? `Re-${label.toLowerCase()}` : label}
            </button>
          )
        })}
      </div>

      {runPhase.error && (
        <div className="text-xs text-red-600 dark:text-red-400">
          {runPhase.error.message}
        </div>
      )}
    </div>
  )
}

function Timeline({
  phasesState,
  currentPhase,
}: {
  phasesState: Record<string, { status?: string }>
  currentPhase: string
}) {
  const phases = ['ARCHITECTURE_DECISION', 'DOCKER', 'TERRAFORM', 'KUBERNETES', 'CICD']
  return (
    <ol className="flex items-center gap-1 overflow-x-auto pb-1">
      {phases.map((p, i) => {
        const status = phasesState[p]?.status
        const isCurrent = p === currentPhase
        const tone =
          status === 'completed'
            ? 'bg-emerald-500'
            : status === 'failed'
              ? 'bg-red-500'
              : status === 'awaiting_input'
                ? 'bg-amber-500'
                : isCurrent
                  ? 'bg-brand-500 animate-pulse'
                  : 'bg-slate-300 dark:bg-white/10'
        return (
          <li key={p} className="flex items-center gap-1 shrink-0">
            <span className={cn('w-2 h-2 rounded-full', tone)} />
            <span className="text-[10px] uppercase tracking-wider text-slate-500">{p}</span>
            {i < phases.length - 1 && (
              <span className="w-4 h-px bg-slate-200 dark:bg-white/[0.06] mx-1" />
            )}
          </li>
        )
      })}
    </ol>
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
