import { useState } from 'react'
import {
  Brain,
  Boxes,
  Cog,
  Code2,
  Container,
  Cpu,
  DollarSign,
  FileSearch,
  GitBranch,
  Layers,
  ShieldCheck,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import { useProjectContext } from '@/hooks/useProjects'
import { cn, timeAgo } from '@/lib/utils'
import type { ProjectContextResponse } from '@/types/project'

interface Props {
  projectId: string
}

// Pretty labels + icons for each known context_type. Unknown types still
// render — they just fall back to a generic icon and the raw type string.
const META: Record<string, { label: string; icon: React.ElementType; tone: string }> = {
  repository_summary:     { label: 'Repository summary',     icon: GitBranch,   tone: 'text-brand-600 dark:text-brand-400' },
  detected_stack:         { label: 'Detected stack',         icon: Code2,       tone: 'text-emerald-600 dark:text-emerald-400' },
  detected_services:      { label: 'Detected services',      icon: Boxes,       tone: 'text-emerald-600 dark:text-emerald-400' },
  architecture_decision:  { label: 'Architecture decision',  icon: Layers,      tone: 'text-purple-600 dark:text-purple-400' },
  selected_plan:          { label: 'Selected plan',          icon: ShieldCheck, tone: 'text-emerald-600 dark:text-emerald-400' },
  docker_hints:           { label: 'Docker hints',           icon: Container,   tone: 'text-sky-600 dark:text-sky-400' },
  terraform_hints:        { label: 'Terraform hints',        icon: Cpu,         tone: 'text-amber-600 dark:text-amber-400' },
  infrastructure_summary: { label: 'Infrastructure summary', icon: Boxes,       tone: 'text-slate-600 dark:text-slate-300' },
  validation_summary:     { label: 'Validation summary',     icon: ShieldCheck, tone: 'text-rose-600 dark:text-rose-400' },
  cost_summary:           { label: 'Cost summary',           icon: DollarSign,  tone: 'text-emerald-600 dark:text-emerald-400' },
}

export function ProjectContextPanel({ projectId }: Props) {
  const { data, isLoading, error } = useProjectContext(projectId)

  if (isLoading) return <Skeleton />
  if (error)
    return (
      <div className="p-4 rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10 text-xs text-red-700 dark:text-red-300">
        Failed to load project context: {(error as Error).message}
      </div>
    )

  const rows = data ?? []

  if (!rows.length) {
    return (
      <div className="p-6 rounded-xl text-center border border-dashed border-slate-200 dark:border-white/[0.08]">
        <Brain className="w-8 h-8 mx-auto text-slate-300 dark:text-slate-700 mb-3" />
        <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
          No project context yet
        </div>
        <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto">
          Run the analysis or planning phase — repository insights, detected
          stack, and architecture recommendations will be captured here for
          reuse across future workflows.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <header className="flex items-center gap-2">
        <Brain className="w-4 h-4 text-brand-600 dark:text-brand-400" />
        <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
          Project intelligence
        </h2>
        <span className="text-[10px] text-slate-500 px-2 py-0.5 rounded-full bg-slate-100 dark:bg-white/[0.04]">
          {rows.length} {rows.length === 1 ? 'digest' : 'digests'}
        </span>
      </header>
      <p className="text-xs text-slate-500 max-w-2xl">
        Persistent memory built from every workflow phase. Reused by reruns,
        recommendations, and the upcoming RAG layer.
      </p>

      <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {rows.map((ctx) => (
          <ContextCard key={ctx.id} ctx={ctx} />
        ))}
      </ul>
    </div>
  )
}

function ContextCard({ ctx }: { ctx: ProjectContextResponse }) {
  const [open, setOpen] = useState(false)
  const meta = META[ctx.context_type] ?? {
    label: ctx.context_type,
    icon: FileSearch,
    tone: 'text-slate-500',
  }
  const Icon = meta.icon
  const summary = summarize(ctx)

  return (
    <li
      className={cn(
        'rounded-xl border border-slate-200 dark:border-white/[0.06]',
        'bg-white dark:bg-surface-800/40',
      )}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left p-3 flex items-start gap-3"
      >
        <Icon className={cn('w-4 h-4 mt-0.5 shrink-0', meta.tone)} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs font-semibold text-slate-800 dark:text-slate-200 truncate">
              {meta.label}
            </div>
            <div className="flex items-center gap-2 shrink-0 text-[10px] text-slate-400">
              <span>{timeAgo(ctx.updated_at)}</span>
              {open ? (
                <ChevronDown className="w-3 h-3" />
              ) : (
                <ChevronRight className="w-3 h-3" />
              )}
            </div>
          </div>
          {summary && (
            <p className="text-[11px] text-slate-500 mt-1 line-clamp-2">{summary}</p>
          )}
          {ctx.generated_by && (
            <div className="text-[10px] text-slate-400 mt-1">
              <Cog className="w-2.5 h-2.5 inline -mt-0.5 mr-1" />
              by {ctx.generated_by}
            </div>
          )}
        </div>
      </button>
      {open && (
        <pre className="text-[11px] font-mono text-slate-600 dark:text-slate-400 bg-slate-50 dark:bg-surface-900/40 px-3 py-2 overflow-auto max-h-72 border-t border-slate-100 dark:border-white/[0.04] whitespace-pre-wrap break-words">
          {JSON.stringify(ctx.content, null, 2)}
        </pre>
      )}
    </li>
  )
}

function summarize(ctx: ProjectContextResponse): string | null {
  const c = ctx.content ?? {}
  switch (ctx.context_type) {
    case 'repository_summary': {
      const lang = (c.language as string) || 'unknown'
      // application_profile is an OBJECT in the digest, not a string —
      // pluck the human-meaningful field out instead of dumping [object Object].
      const profileObj = (c.application_profile as Record<string, unknown> | string | null) ?? null
      const profile =
        typeof profileObj === 'string'
          ? profileObj
          : (profileObj?.application_type as string) ?? 'unknown'
      const services = (c.service_count as number) ?? 0
      return `${lang} · ${profile} · ${services} service(s)`
    }
    case 'detected_stack': {
      const frameworks = (c.frameworks as string[]) ?? []
      if (frameworks.length) return frameworks.slice(0, 5).join(', ')
      // Fall back to runtime/language when frameworks empty — otherwise the
      // card renders nameless and the user has to expand to see anything.
      const runtime = (c.runtime as string) || (c.language as string) || null
      return runtime || null
    }
    case 'detected_services': {
      const services = (c.services as unknown[]) ?? []
      return `${services.length} service(s)`
    }
    case 'architecture_decision': {
      const plans = (c.plans as Array<{ id: string; monthly_cost: number }>) ?? []
      const rec = c.recommended_plan ?? '—'
      return plans.length
        ? `${plans.length} strategies · recommended: ${rec}`
        : null
    }
    case 'selected_plan': {
      const id = c.selected_plan_id ?? '—'
      const cost = c.monthly_cost as number | undefined
      return cost ? `${id} · $${cost.toFixed(2)}/mo` : (id as string)
    }
    case 'docker_hints':
      return [c.base_image, c.distro, c.build_strategy].filter(Boolean).join(' · ')
    case 'terraform_hints':
      return [c.provider, c.region, `${(c.modules as unknown[])?.length ?? 0} modules`]
        .filter(Boolean)
        .join(' · ')
    case 'validation_summary': {
      const status = c.status as string
      const issues = (c.quality_issues as unknown[])?.length ?? 0
      return `${status ?? 'unknown'} · ${issues} issue(s)`
    }
    case 'cost_summary': {
      const cost = c.monthly_cost as number | undefined
      return cost ? `$${cost.toFixed(2)}/month — ${c.cost_profile}` : null
    }
    case 'infrastructure_summary': {
      const n = (c.artifact_count as number) ?? 0
      return `${n} artifact(s) generated`
    }
    default:
      return null
  }
}

function Skeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="h-20 rounded-xl border border-slate-200 dark:border-white/[0.06] bg-white dark:bg-surface-800/40 animate-pulse"
        />
      ))}
    </div>
  )
}
