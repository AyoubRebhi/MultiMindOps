import {
  LayoutGrid,
  Shield,
  Container,
  Layers,
  Ship,
  GitBranch,
  CheckCircle2,
  AlertTriangle,
  Info,
} from 'lucide-react'
import { StepContainer } from '@/components/workflow/StepContainer'
import { useWorkflowStore } from '@/store/workflowStore'
import {
  getSummary,
  getInfraArtifacts,
  getTerraformArtifacts,
  getKubernetesArtifacts,
  getCicdArtifacts,
  displayName,
} from '@/services/workflowApi'
import { cn } from '@/lib/utils'
import type { TaskResult } from '@/types'

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  count,
  color,
  files,
}: {
  icon: React.ElementType
  label: string
  count: number
  color: string
  files: string[]
}) {
  return (
    <div className={cn(
      'rounded-xl border p-4 space-y-3',
      'bg-white dark:bg-surface-900',
      'border-slate-200 dark:border-white/[0.06]',
    )}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className={cn('w-4 h-4', color)} />
          <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{label}</span>
        </div>
        <span className={cn(
          'px-2 py-0.5 rounded-full text-xs font-bold',
          count > 0
            ? 'bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300'
            : 'bg-slate-100 dark:bg-surface-800 text-slate-400 dark:text-slate-600',
        )}>
          {count}
        </span>
      </div>
      {files.length > 0 && (
        <ul className="space-y-1">
          {files.map((f) => (
            <li key={f} className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
              <CheckCircle2 className="w-3 h-3 text-emerald-500 shrink-0" />
              <span className="font-mono truncate">{f}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── Security notes ────────────────────────────────────────────────────────────

function SecurityNotes({ security }: { security: TaskResult | undefined }) {
  const sec = security?.security
  if (!sec) return null

  const score = sec.score ?? 0
  const grade = sec.grade ?? '-'

  return (
    <div className={cn(
      'rounded-xl border p-4',
      'bg-white dark:bg-surface-900',
      'border-slate-200 dark:border-white/[0.06]',
    )}>
      <div className="flex items-center gap-3 mb-3">
        <Shield className="w-4 h-4 text-rose-500 dark:text-rose-400" />
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">Security Analysis</span>
        <div className="ml-auto flex items-center gap-2">
          <span className={cn(
            'px-2 py-0.5 rounded-full text-sm font-bold',
            score >= 80 ? 'bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300'
            : score >= 60 ? 'bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300'
            : 'bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-300',
          )}>
            {grade}
          </span>
          <span className="text-xs text-slate-400 dark:text-slate-600">{score}/100</span>
        </div>
      </div>

      {sec.summary && (
        <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed mb-3">{sec.summary}</p>
      )}

      {sec.recommendations && sec.recommendations.length > 0 && (
        <div>
          <p className="text-xs font-medium text-slate-500 dark:text-slate-500 mb-2">Recommendations</p>
          <ul className="space-y-1.5">
            {sec.recommendations.slice(0, 5).map((rec: string, i: number) => (
              <li key={i} className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-400">
                <AlertTriangle className="w-3 h-3 text-amber-500 shrink-0 mt-0.5" />
                {rec}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

interface Props {
  onApprove: () => void
  onBack: () => void
}

export function SummaryStep({ onApprove, onBack }: Props) {
  const { task, userInput, editedArtifacts } = useWorkflowStore()

  const summary      = task ? getSummary(task) : ''
  const infra        = task ? getInfraArtifacts(task) : {}
  const terraform    = task ? getTerraformArtifacts(task) : {}
  const kubernetes   = task ? getKubernetesArtifacts(task) : {}
  const cicd         = task ? getCicdArtifacts(task) : {}
  const hasEdits     = Object.keys(editedArtifacts).length > 0

  const infraFiles      = Object.keys(infra).map(displayName)
  const terraformFiles  = Object.keys(terraform).map(displayName)
  const kubernetesFiles = Object.keys(kubernetes).map(displayName)
  const cicdFiles       = Object.keys(cicd).map(displayName)

  return (
    <StepContainer
      onBack={onBack}
      onApprove={onApprove}
      approveLabel="Continue to CI/CD"
    >
      <div className="max-w-3xl space-y-6">

        {/* Header */}
        <div className={cn(
          'flex items-start gap-3 px-4 py-3 rounded-xl',
          'bg-gradient-to-br from-brand-50 to-purple-50 dark:from-brand-600/10 dark:to-purple-600/10',
          'border border-brand-200 dark:border-brand-500/20',
        )}>
          <LayoutGrid className="w-5 h-5 text-brand-500 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-brand-800 dark:text-brand-200">Architecture Overview</p>
            <p className="text-xs text-brand-700/70 dark:text-brand-400/60 mt-0.5 font-mono truncate">
              {userInput.repo_url}
            </p>
          </div>
        </div>

        {/* AI-generated summary */}
        {summary && (
          <div className={cn(
            'rounded-xl border p-4',
            'bg-white dark:bg-surface-900',
            'border-slate-200 dark:border-white/[0.06]',
          )}>
            <div className="flex items-center gap-2 mb-3">
              <Info className="w-4 h-4 text-brand-500" />
              <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">AI Summary</span>
            </div>
            <p className="text-sm text-slate-600 dark:text-slate-400 leading-relaxed whitespace-pre-wrap">
              {summary}
            </p>
          </div>
        )}

        {/* Artifact stats grid */}
        <div>
          <p className="text-xs font-medium text-slate-400 dark:text-slate-600 uppercase tracking-wider mb-3">
            Generated Artifacts
          </p>
          <div className="grid grid-cols-2 gap-3">
            <StatCard
              icon={Container}
              label="Infrastructure"
              count={infraFiles.length}
              color="text-cyan-600 dark:text-cyan-400"
              files={infraFiles}
            />
            <StatCard
              icon={Layers}
              label="Terraform"
              count={terraformFiles.length}
              color="text-orange-600 dark:text-orange-400"
              files={terraformFiles}
            />
            <StatCard
              icon={Ship}
              label="Kubernetes"
              count={kubernetesFiles.length}
              color="text-blue-600 dark:text-blue-400"
              files={kubernetesFiles}
            />
            <StatCard
              icon={GitBranch}
              label="CI/CD"
              count={cicdFiles.length}
              color="text-purple-600 dark:text-purple-400"
              files={cicdFiles}
            />
          </div>
        </div>

        {/* Edited artifacts notice */}
        {hasEdits && (
          <div className={cn(
            'flex items-start gap-3 px-4 py-3 rounded-xl',
            'bg-amber-50 dark:bg-amber-500/10',
            'border border-amber-200 dark:border-amber-500/20',
          )}>
            <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
                {Object.keys(editedArtifacts).length} artifact{Object.keys(editedArtifacts).length > 1 ? 's' : ''} edited
              </p>
              <p className="text-xs text-amber-700/70 dark:text-amber-400/60 mt-0.5">
                Your changes will be submitted to the backend in the final step.
              </p>
            </div>
          </div>
        )}

        {/* Security notes */}
        {task?.result && <SecurityNotes security={task.result} />}
      </div>
    </StepContainer>
  )
}
