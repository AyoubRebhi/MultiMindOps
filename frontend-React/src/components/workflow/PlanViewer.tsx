import {
  Cpu,
  GitBranch,
  Layers,
  FileCode,
  Zap,
  BarChart3,
  CheckCircle2,
  AlertCircle,
  Tag,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PlanData } from '@/types'

interface Props {
  plan: PlanData
  className?: string
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
const ARTIFACT_META: Record<string, { icon: React.ElementType; color: string }> = {
  dockerfile:     { icon: FileCode, color: 'text-blue-500 dark:text-blue-400' },
  docker_compose: { icon: Layers,   color: 'text-sky-500 dark:text-sky-400' },
  kubernetes:     { icon: Layers,   color: 'text-indigo-500 dark:text-indigo-400' },
  k8s:            { icon: Layers,   color: 'text-indigo-500 dark:text-indigo-400' },
  terraform:      { icon: Cpu,      color: 'text-purple-500 dark:text-purple-400' },
  github_actions: { icon: GitBranch, color: 'text-emerald-500 dark:text-emerald-400' },
  ci:             { icon: GitBranch, color: 'text-emerald-500 dark:text-emerald-400' },
  cicd:           { icon: GitBranch, color: 'text-emerald-500 dark:text-emerald-400' },
}

function resolveArtifactMeta(name: string) {
  const lower = name.toLowerCase()
  for (const [key, meta] of Object.entries(ARTIFACT_META)) {
    if (lower.includes(key)) return meta
  }
  return { icon: FileCode, color: 'text-slate-400 dark:text-slate-500' }
}

const COMPLEXITY_COLORS: Record<string, string> = {
  low:    'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-500/30',
  medium: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-500/30',
  high:   'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-300 border-red-200 dark:border-red-500/30',
}

// ─── Sub-sections ─────────────────────────────────────────────────────────────
function SectionHeader({ icon: Icon, title }: { icon: React.ElementType; title: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="w-4 h-4 text-brand-500 dark:text-brand-400 shrink-0" />
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 tracking-wide uppercase text-[11px]">
        {title}
      </h3>
    </div>
  )
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        'rounded-xl border p-4',
        'bg-white dark:bg-surface-800/40',
        'border-slate-100 dark:border-white/[0.06]',
        className
      )}
    >
      {children}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────
export function PlanViewer({ plan, className }: Props) {
  const summary = plan.summary ?? plan.reasoning_summary
  const artifacts: string[] = plan.artifacts ?? (plan.required_artifacts as string[] | undefined) ?? []
  const technologies: string[] = (plan.technologies as string[] | undefined) ?? []
  const steps: string[] = (plan.steps as string[] | undefined) ?? []
  const complexity = (plan.estimated_complexity as string | undefined)?.toLowerCase()
  const score = plan.plan_score as number | undefined
  const variant = plan.plan_variant as string | undefined
  const description = plan.plan_description as string | undefined
  const estimatedSteps = plan.estimated_steps

  return (
    <div className={cn('space-y-4 animate-slide-in', className)}>

      {/* ── Architecture summary ──────────────────────────────────────── */}
      {(summary || description) && (
        <Card className="bg-brand-50/60 dark:bg-brand-600/5 border-brand-100 dark:border-brand-500/15">
          <SectionHeader icon={Cpu} title="Architecture Summary" />
          <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
            {summary ?? description}
          </p>
          {description && summary && description !== summary && (
            <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed mt-2">
              {description}
            </p>
          )}
        </Card>
      )}

      {/* ── Meta row: variant, complexity, score, steps ────────────────── */}
      <div className="flex flex-wrap gap-2">
        {variant && (
          <span className={cn(
            'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border',
            'bg-slate-50 dark:bg-surface-800/60',
            'text-slate-600 dark:text-slate-400',
            'border-slate-200 dark:border-white/[0.08]'
          )}>
            <Tag className="w-3 h-3" />
            {variant}
          </span>
        )}
        {complexity && COMPLEXITY_COLORS[complexity] && (
          <span className={cn(
            'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border',
            COMPLEXITY_COLORS[complexity]
          )}>
            <BarChart3 className="w-3 h-3" />
            {complexity.charAt(0).toUpperCase() + complexity.slice(1)} complexity
          </span>
        )}
        {estimatedSteps != null && (
          <span className={cn(
            'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border',
            'bg-slate-50 dark:bg-surface-800/60',
            'text-slate-600 dark:text-slate-400',
            'border-slate-200 dark:border-white/[0.08]'
          )}>
            <Zap className="w-3 h-3" />
            {estimatedSteps} step{estimatedSteps !== 1 ? 's' : ''}
          </span>
        )}
        {score != null && (
          <span className={cn(
            'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border',
            score >= 0.8
              ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-500/30'
              : score >= 0.5
              ? 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-500/30'
              : 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-300 border-red-200 dark:border-red-500/30'
          )}>
            <CheckCircle2 className="w-3 h-3" />
            Score: {Math.round(score * 100)}%
          </span>
        )}
      </div>

      {/* ── Infrastructure decisions (artifacts) ───────────────────────── */}
      {artifacts.length > 0 && (
        <Card>
          <SectionHeader icon={Layers} title="Infrastructure Decisions" />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {artifacts.map((art) => {
              const { icon: Icon, color } = resolveArtifactMeta(art)
              return (
                <div
                  key={art}
                  className={cn(
                    'flex items-center gap-3 px-3 py-2.5 rounded-lg',
                    'bg-slate-50 dark:bg-surface-800/60',
                    'border border-slate-100 dark:border-white/[0.04]',
                    'transition-colors'
                  )}
                >
                  <Icon className={cn('w-4 h-4 shrink-0', color)} />
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-300 truncate">
                    {art}
                  </span>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* ── Services / Technologies ─────────────────────────────────────── */}
      {technologies.length > 0 && (
        <Card>
          <SectionHeader icon={GitBranch} title="Services &amp; Technologies" />
          <div className="flex flex-wrap gap-2">
            {technologies.map((t) => (
              <span
                key={t}
                className={cn(
                  'px-2.5 py-1 rounded-md text-xs font-mono font-medium',
                  'bg-brand-50 dark:bg-brand-600/10',
                  'text-brand-700 dark:text-brand-300',
                  'border border-brand-100 dark:border-brand-500/20'
                )}
              >
                {t}
              </span>
            ))}
          </div>
        </Card>
      )}

      {/* ── Planned steps ──────────────────────────────────────────────── */}
      {steps.length > 0 && (
        <Card>
          <SectionHeader icon={CheckCircle2} title="Execution Steps" />
          <ol className="space-y-2">
            {steps.map((step, i) => (
              <li key={i} className="flex items-start gap-3">
                <div className={cn(
                  'flex items-center justify-center w-5 h-5 rounded-full shrink-0 mt-0.5',
                  'bg-brand-50 dark:bg-brand-600/20',
                  'border border-brand-200 dark:border-brand-500/30',
                  'text-[10px] font-mono font-medium text-brand-600 dark:text-brand-400'
                )}>
                  {i + 1}
                </div>
                <span className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
                  {String(step)}
                </span>
              </li>
            ))}
          </ol>
        </Card>
      )}

      {/* Empty state */}
      {!summary && !description && artifacts.length === 0 && technologies.length === 0 && steps.length === 0 && (
        <Card className="flex items-center gap-3 py-6">
          <AlertCircle className="w-5 h-5 text-amber-500 dark:text-amber-400 shrink-0" />
          <p className="text-sm text-slate-500 dark:text-slate-400">
            The plan was generated but contains no detailed breakdown. You can still approve or request changes.
          </p>
        </Card>
      )}
    </div>
  )
}
