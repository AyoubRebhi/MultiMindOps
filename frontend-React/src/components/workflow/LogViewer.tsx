import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { LogEntry } from '@/types'

// ── Phase detection ───────────────────────────────────────────────────────────

type Phase =
  | 'analysis'
  | 'planning'
  | 'docker'
  | 'terraform'
  | 'kubernetes'
  | 'security'
  | 'validation'
  | 'cicd'
  | 'other'

const PHASE_META: Record<Phase, { label: string; color: string; dotColor: string }> = {
  analysis:   { label: 'Repository Analysis', color: 'text-slate-700 dark:text-slate-200',    dotColor: 'bg-slate-400' },
  planning:   { label: 'Planning',            color: 'text-brand-700 dark:text-brand-300',    dotColor: 'bg-brand-500' },
  docker:     { label: 'Docker Generation',   color: 'text-cyan-700 dark:text-cyan-300',      dotColor: 'bg-cyan-500' },
  terraform:  { label: 'Terraform',           color: 'text-orange-700 dark:text-orange-300',  dotColor: 'bg-orange-500' },
  kubernetes: { label: 'Kubernetes',          color: 'text-blue-700 dark:text-blue-300',      dotColor: 'bg-blue-500' },
  security:   { label: 'Security Scan',       color: 'text-rose-700 dark:text-rose-300',      dotColor: 'bg-rose-500' },
  validation: { label: 'Validation',          color: 'text-teal-700 dark:text-teal-300',      dotColor: 'bg-teal-500' },
  cicd:       { label: 'CI/CD',               color: 'text-purple-700 dark:text-purple-300',  dotColor: 'bg-purple-500' },
  other:      { label: 'System',              color: 'text-slate-600 dark:text-slate-400',    dotColor: 'bg-slate-300' },
}

function detectPhase(log: LogEntry): Phase {
  const agent = String(log.agent ?? log.step ?? '').toLowerCase()
  const msg   = String(log.message ?? log.step ?? '').toLowerCase()

  if (agent.includes('codebaseanalysis') || agent.includes('codebase_analysis') || msg.includes('repository analysis') || msg.includes('analyzing repo')) return 'analysis'
  if (agent.includes('planneragent') || agent.includes('multiplanagent') || agent.includes('costestimation') || msg.includes('planning') || msg.includes('generating plan')) return 'planning'
  if (agent.includes('infrastructureagent') || msg.includes('dockerfile') || msg.includes('docker compose')) return 'docker'
  if (agent.includes('terraformagent') || msg.includes('terraform') || msg.includes('hcl')) return 'terraform'
  if (agent.includes('kubernetesagent') || msg.includes('kubernetes') || msg.includes('k8s')) return 'kubernetes'
  if (agent.includes('security_scan') || msg.includes('security scan') || msg.includes('security placeholder')) return 'security'
  if (agent.includes('validat') || msg.includes('validat') || msg.includes('artifact quality')) return 'validation'
  if (agent.includes('cicdagent') || msg.includes('ci/cd') || msg.includes('github actions') || msg.includes('cicd')) return 'cicd'
  return 'other'
}

// ── Log entry rendering ───────────────────────────────────────────────────────

function levelStyle(level?: string) {
  switch (level) {
    case 'error':   return 'text-red-600 dark:text-red-400'
    case 'warning': return 'text-amber-600 dark:text-amber-400'
    case 'success': return 'text-emerald-600 dark:text-emerald-400'
    case 'debug':   return 'text-slate-400 dark:text-slate-500'
    default:        return 'text-slate-700 dark:text-slate-300'
  }
}

function levelPrefix(level?: string) {
  switch (level) {
    case 'error':   return '✗'
    case 'warning': return '⚠'
    case 'success': return '✓'
    default:        return '›'
  }
}

function LogLine({ log, index }: { log: LogEntry; index: number }) {
  const msg   = typeof log === 'string' ? log : log.message ?? log.step ?? JSON.stringify(log)
  const level = typeof log === 'object' ? log.level : undefined
  const agent = typeof log === 'object' ? (log.agent ?? log.step) : undefined
  const ts    = typeof log === 'object' ? log.timestamp : undefined

  return (
    <div key={index} className={cn('flex gap-2 py-0.5', levelStyle(level))}>
      <span className="text-slate-400 dark:text-slate-600 shrink-0">{levelPrefix(level)}</span>
      {ts && (
        <span className="text-slate-400 dark:text-slate-600 shrink-0">
          {new Date(ts as string).toLocaleTimeString()}
        </span>
      )}
      {agent && (
        <span className="text-brand-600 dark:text-brand-500 shrink-0">
          [{String(agent)}]
        </span>
      )}
      <span className="break-all">{String(msg)}</span>
    </div>
  )
}

// ── Phase section (collapsible) ───────────────────────────────────────────────

function PhaseSection({
  phase,
  logs,
  defaultOpen,
}: {
  phase: Phase
  logs: LogEntry[]
  defaultOpen: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const { label, color, dotColor } = PHASE_META[phase]
  const hasError = logs.some(l => (l as LogEntry).level === 'error')

  return (
    <div>
      <button
        onClick={() => setOpen(o => !o)}
        className={cn(
          'w-full flex items-center gap-2 px-3 py-1.5 text-left transition-colors',
          'bg-slate-50 dark:bg-surface-800/50',
          'hover:bg-slate-100 dark:hover:bg-white/[0.04]',
          'border-b border-slate-200 dark:border-white/[0.04]',
        )}
      >
        {open
          ? <ChevronDown className="w-3 h-3 text-slate-400 dark:text-slate-500 shrink-0" />
          : <ChevronRight className="w-3 h-3 text-slate-400 dark:text-slate-500 shrink-0" />
        }
        <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', dotColor)} />
        <span className={cn('text-xs font-semibold', color)}>{label}</span>
        <span className="ml-auto text-[10px] text-slate-400 dark:text-slate-500 font-mono">
          {logs.length} lines
        </span>
        {hasError && (
          <span className="text-[10px] text-red-500 dark:text-red-400 font-medium">✗ error</span>
        )}
      </button>

      {open && (
        <div className="px-3 py-2 font-mono text-xs space-y-0">
          {logs.map((log, i) => <LogLine key={i} log={log} index={i} />)}
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  logs: LogEntry[]
  className?: string
  autoScroll?: boolean
  grouped?: boolean
}

export function LogViewer({ logs, className, autoScroll = true, grouped = true }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, autoScroll])

  if (!logs.length) {
    return (
      <div className={cn(
        'flex items-center justify-center h-32 text-sm',
        'text-slate-400 dark:text-slate-600',
        className,
      )}>
        No logs yet…
      </div>
    )
  }

  if (!grouped) {
    // Flat view (fallback / legacy)
    return (
      <div className={cn(
        'font-mono text-xs overflow-y-auto p-4 space-y-0.5 rounded-lg',
        'bg-slate-50 dark:bg-surface-950',
        'border border-slate-200 dark:border-white/[0.06]',
        className ?? 'h-64',
      )}>
        {logs.map((log, i) => <LogLine key={i} log={log} index={i} />)}
        <div ref={bottomRef} />
      </div>
    )
  }

  // Grouped view
  const phaseOrder: Phase[] = ['analysis', 'planning', 'docker', 'terraform', 'kubernetes', 'security', 'validation', 'cicd', 'other']
  const grouped_: Partial<Record<Phase, LogEntry[]>> = {}

  for (const log of logs) {
    const phase = detectPhase(log)
    if (!grouped_[phase]) grouped_[phase] = []
    grouped_[phase]!.push(log)
  }

  const activePhasesOrdered = phaseOrder.filter(p => grouped_[p]?.length)

  // Default-open the last phase that has logs (most recent activity)
  const lastPhase = activePhasesOrdered[activePhasesOrdered.length - 1]

  return (
    <div className={cn(
      'rounded-lg overflow-hidden',
      'bg-slate-50 dark:bg-surface-950',
      'border border-slate-200 dark:border-white/[0.06]',
      className ?? 'max-h-[32rem] overflow-y-auto',
    )}>
      {activePhasesOrdered.map(phase => (
        <PhaseSection
          key={phase}
          phase={phase}
          logs={grouped_[phase]!}
          defaultOpen={phase === lastPhase}
        />
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
