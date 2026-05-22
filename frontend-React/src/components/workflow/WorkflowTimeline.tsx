import { useMemo } from 'react'
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  AlertTriangle,
  RotateCcw,
  SkipForward,
  ShieldCheck,
  FileCheck2,
  AlertOctagon,
  Container,
  Boxes,
  Cpu,
  GitBranch,
  Layers,
  FileSearch,
} from 'lucide-react'
import { cn, timeAgo } from '@/lib/utils'
import type { ArtifactResponse, WorkflowResponse } from '@/types/project'

/* eslint-disable react-refresh/only-export-components */

interface Props {
  workflow: WorkflowResponse
  /** Artifacts persisted for the project — used for per-phase counters. */
  artifacts: ArtifactResponse[]
}

// Canonical phase ordering rendered top-to-bottom. The key matches the
// uppercase key written by WorkflowOrchestrationService into phases_state.
const PHASES: Array<{
  key: string
  label: string
  icon: React.ElementType
  artifactTypes: string[]
}> = [
  { key: 'ARCHITECTURE_DECISION', label: 'Analysis & planning', icon: FileSearch,  artifactTypes: ['analysis', 'architecture_plan'] },
  { key: 'PLAN_SELECTED',         label: 'Plan selection',       icon: Layers,      artifactTypes: [] },
  { key: 'DOCKER',                label: 'Docker',               icon: Container,   artifactTypes: ['docker'] },
  { key: 'TERRAFORM',             label: 'Terraform',            icon: Boxes,       artifactTypes: ['terraform'] },
  { key: 'VALIDATION',            label: 'Validation',           icon: ShieldCheck, artifactTypes: ['validation_report'] },
  { key: 'KUBERNETES',            label: 'Kubernetes',           icon: Cpu,         artifactTypes: ['kubernetes'] },
  { key: 'CICD',                  label: 'CI/CD pipeline',       icon: GitBranch,   artifactTypes: ['cicd'] },
]

interface PhaseEntry {
  status?: string
  updated_at?: string
  started_at?: string
  completed_at?: string
  duration_ms?: number
  retries?: number
  skipped?: boolean
  replayed?: boolean
  validator_findings?: number
  warnings?: number
  artifact_count?: number
}

/**
 * Vertical timeline of every workflow phase. Reads ``workflow.phases_state``
 * (written by ``WorkflowOrchestrationService._record_phase``) and decorates
 * each phase with status, duration, validator findings, artifact counts,
 * approval rollups, and retry / replay / skip indicators.
 */
export function WorkflowTimeline({ workflow, artifacts }: Props) {
  const phasesState = (workflow.phases_state ?? {}) as Record<string, PhaseEntry>

  const artifactCounts = useMemo(() => {
    const out: Record<string, { total: number; warnings: number; approved: number }> = {}
    for (const a of artifacts) {
      const slot = out[a.artifact_type] ??= { total: 0, warnings: 0, approved: 0 }
      slot.total += 1
      if (a.validation_status === 'failed') slot.warnings += 1
      if (a.approval_state === 'approved') slot.approved += 1
    }
    return out
  }, [artifacts])

  return (
    <div className="rounded-xl border border-slate-200 dark:border-white/[0.06] bg-white dark:bg-surface-800/40">
      <header className="flex items-center justify-between px-4 py-3 border-b border-slate-100 dark:border-white/[0.04]">
        <div className="flex items-center gap-2">
          <FileCheck2 className="w-4 h-4 text-brand-600 dark:text-brand-400" />
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
            Workflow timeline
          </h3>
        </div>
        <div className="text-[10px] text-slate-500">
          {workflow.id.slice(0, 8)}… · started {timeAgo(workflow.created_at)}
        </div>
      </header>

      <ol className="p-4 space-y-3">
        {PHASES.map((phase, idx) => {
          const entry = phasesState[phase.key] ?? {}
          const counts = phase.artifactTypes.reduce(
            (acc, t) => {
              const c = artifactCounts[t]
              if (c) {
                acc.total += c.total
                acc.warnings += c.warnings
                acc.approved += c.approved
              }
              return acc
            },
            { total: 0, warnings: 0, approved: 0 },
          )
          return (
            <PhaseRow
              key={phase.key}
              phaseLabel={phase.label}
              Icon={phase.icon}
              entry={entry}
              isLast={idx === PHASES.length - 1}
              artifactCounts={counts}
            />
          )
        })}
      </ol>

      {workflow.error_message && (
        <div className="px-4 pb-4">
          <div className="rounded-lg border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10 p-3 text-xs text-red-700 dark:text-red-300 flex items-start gap-2">
            <AlertOctagon className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <span className="whitespace-pre-wrap break-words">{workflow.error_message}</span>
          </div>
        </div>
      )}
    </div>
  )
}

function PhaseRow({
  phaseLabel,
  Icon,
  entry,
  isLast,
  artifactCounts,
}: {
  phaseLabel: string
  Icon: React.ElementType
  entry: PhaseEntry
  isLast: boolean
  artifactCounts: { total: number; warnings: number; approved: number }
}) {
  const status = entry.status ?? 'pending'
  const tone = phaseTone(status)
  const StateIcon = phaseIcon(status)
  const indicators: Array<{ icon: React.ElementType; label: string; tone: string }> = []
  if (entry.retries && entry.retries > 0) {
    indicators.push({ icon: RotateCcw, label: `${entry.retries}× retry`, tone: 'text-amber-600 dark:text-amber-400' })
  }
  if (entry.skipped) {
    indicators.push({ icon: SkipForward, label: 'skipped', tone: 'text-slate-500' })
  }
  if (entry.replayed) {
    indicators.push({ icon: RotateCcw, label: 'replay', tone: 'text-sky-600 dark:text-sky-400' })
  }
  if (entry.validator_findings && entry.validator_findings > 0) {
    indicators.push({
      icon: AlertTriangle,
      label: `${entry.validator_findings} finding(s)`,
      tone: 'text-amber-600 dark:text-amber-400',
    })
  }
  if (entry.warnings && entry.warnings > 0) {
    indicators.push({
      icon: AlertTriangle,
      label: `${entry.warnings} warning(s)`,
      tone: 'text-amber-600 dark:text-amber-400',
    })
  }
  if (artifactCounts.total > 0) {
    indicators.push({
      icon: FileCheck2,
      label: `${artifactCounts.total} artifact(s)${artifactCounts.approved ? `, ${artifactCounts.approved} approved` : ''}`,
      tone: 'text-slate-500',
    })
  }

  return (
    <li className="relative pl-9">
      {/* Vertical thread */}
      {!isLast && (
        <span
          aria-hidden
          className="absolute left-3 top-7 bottom-[-12px] w-px bg-slate-200 dark:bg-white/[0.06]"
        />
      )}

      {/* Bullet */}
      <span
        className={cn(
          'absolute left-0 top-0 w-6 h-6 rounded-full grid place-items-center border',
          tone.bullet,
        )}
      >
        <StateIcon className={cn('w-3 h-3', status === 'running' && 'animate-spin')} />
      </span>

      <div className="space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <Icon className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          <span className="text-sm font-medium text-slate-800 dark:text-slate-200">
            {phaseLabel}
          </span>
          <span
            className={cn(
              'text-[10px] px-2 py-0.5 rounded-full border',
              tone.badge,
            )}
          >
            {status}
          </span>
          {entry.duration_ms != null && (
            <span className="text-[10px] text-slate-400 flex items-center gap-1">
              <Clock className="w-3 h-3" /> {formatDuration(entry.duration_ms)}
            </span>
          )}
          {entry.updated_at && (
            <span className="text-[10px] text-slate-400">
              updated {timeAgo(entry.updated_at)}
            </span>
          )}
        </div>
        {indicators.length > 0 && (
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {indicators.map((ind, i) => {
              const Iind = ind.icon
              return (
                <span
                  key={i}
                  className={cn('text-[10px] inline-flex items-center gap-1', ind.tone)}
                >
                  <Iind className="w-3 h-3" />
                  {ind.label}
                </span>
              )
            })}
          </div>
        )}
      </div>
    </li>
  )
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function phaseTone(status: string): { bullet: string; badge: string } {
  switch (status) {
    case 'completed':
      return {
        bullet:
          'bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/30 text-emerald-700 dark:text-emerald-300',
        badge:
          'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-500/30',
      }
    case 'failed':
      return {
        bullet:
          'bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-300',
        badge:
          'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-300 border-red-200 dark:border-red-500/30',
      }
    case 'running':
      return {
        bullet:
          'bg-brand-50 dark:bg-brand-600/15 border-brand-200 dark:border-brand-500/30 text-brand-700 dark:text-brand-300',
        badge:
          'bg-brand-50 dark:bg-brand-600/15 text-brand-700 dark:text-brand-300 border-brand-200 dark:border-brand-500/30',
      }
    case 'awaiting_input':
      return {
        bullet:
          'bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/30 text-amber-700 dark:text-amber-300',
        badge:
          'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-500/30',
      }
    default:
      return {
        bullet:
          'bg-slate-50 dark:bg-white/[0.04] border-slate-200 dark:border-white/[0.06] text-slate-500',
        badge:
          'bg-slate-100 dark:bg-white/[0.04] text-slate-500 dark:text-slate-400 border-slate-200 dark:border-white/[0.06]',
      }
  }
}

function phaseIcon(status: string): React.ElementType {
  switch (status) {
    case 'completed':       return CheckCircle2
    case 'failed':          return XCircle
    case 'running':         return Loader2
    case 'awaiting_input':  return Clock
    default:                return Clock
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60_000)
  const s = Math.round((ms % 60_000) / 1000)
  return `${m}m${s.toString().padStart(2, '0')}s`
}
