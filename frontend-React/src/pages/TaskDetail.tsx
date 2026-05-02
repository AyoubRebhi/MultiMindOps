import { useParams, Link } from 'react-router-dom'
import { useState } from 'react'
import {
  ArrowLeft,
  FileCode,
  Shield,
  GitMerge,
  Terminal,
  RefreshCw,
  AlertCircle,
  Activity,
  DollarSign,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Cloud,
} from 'lucide-react'
import { useTask, useReviewTask } from '@/hooks/useTasks'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { PageLoader } from '@/components/common/LoadingSpinner'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { StatusBadge } from '@/components/common/StatusBadge'
import { LogViewer } from '@/components/workflow/LogViewer'
import { ArtifactReview } from '@/components/workflow/ArtifactReview'
import { ArtifactTabs } from '@/components/artifacts/ArtifactTabs'
import { DiffViewer } from '@/components/artifacts/DiffViewer'
import { ValidationIssues } from '@/components/artifacts/ValidationIssues'
import { SecurityScore } from '@/components/security/SecurityScore'
import { VulnerabilityList } from '@/components/security/VulnerabilityList'
import { PipelineVisualizer } from '@/components/pipeline/PipelineVisualizer'
import { TerraformOutputsPanel } from '@/components/pipeline/TerraformOutputsPanel'
import { formatDate, isTerminalStatus, cn } from '@/lib/utils'
import type { ReviewArtifactsRequest, ValidationResult } from '@/types'

type Tab = 'pipeline' | 'artifacts' | 'terraform' | 'security' | 'diffs' | 'logs'

const TABS: { key: Tab; label: string; icon: React.ElementType }[] = [
  { key: 'pipeline',  label: 'Pipeline',   icon: Activity  },
  { key: 'artifacts', label: 'Artifacts',  icon: FileCode  },
  { key: 'terraform', label: 'Infra',      icon: Cloud     },
  { key: 'security',  label: 'Security',   icon: Shield    },
  { key: 'diffs',     label: 'Diffs',      icon: GitMerge  },
  { key: 'logs',      label: 'Logs',       icon: Terminal  },
]

// Validation panel with color-coded status
function ValidationPanel({ validation }: { validation: ValidationResult }) {
  const { status, missing_artifacts, quality_issues, warnings } = validation
  const statusColors = {
    valid:   { border: 'border-emerald-200 dark:border-emerald-500/20', bg: 'bg-emerald-50 dark:bg-emerald-500/10', icon: CheckCircle2, iconColor: 'text-emerald-500', label: 'Valid' },
    partial: { border: 'border-amber-200 dark:border-amber-500/20',    bg: 'bg-amber-50 dark:bg-amber-500/10',     icon: AlertTriangle, iconColor: 'text-amber-500',   label: 'Partial' },
    invalid: { border: 'border-red-200 dark:border-red-500/20',        bg: 'bg-red-50 dark:bg-red-500/10',         icon: XCircle,       iconColor: 'text-red-500',     label: 'Invalid' },
  }
  const meta = statusColors[status ?? 'partial'] ?? statusColors.partial
  const Icon = meta.icon

  return (
    <div className="space-y-3">
      <div className={cn('flex items-center gap-2 px-4 py-3 rounded-xl border', meta.border, meta.bg)}>
        <Icon className={cn('w-4 h-4 shrink-0', meta.iconColor)} />
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          Artifact Validation — {meta.label}
        </span>
      </div>
      <ValidationIssues validation={validation} />
    </div>
  )
}

// Plan + cost summary strip
function PlanCostStrip({ task }: { task: ReturnType<typeof useTask>['data'] }) {
  if (!task) return null
  const plan = task.plan
  const cost = task.cost_estimation ?? (task.result as Record<string, unknown>)?.cost_estimation as { monthly_cost?: number; cost_profile?: string } | undefined

  const complexityColor: Record<string, string> = {
    low:    'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/20',
    medium: 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/20',
    high:   'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/20',
  }

  if (!plan?.estimated_complexity && !cost?.monthly_cost && !plan?.required_artifacts?.length) return null

  return (
    <div className={cn(
      'flex flex-wrap items-center gap-3 p-4 rounded-xl',
      'bg-white dark:bg-surface-800/40',
      'border border-slate-200 dark:border-white/[0.06]',
    )}>
      {/* Complexity */}
      {plan?.estimated_complexity && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400 dark:text-slate-500">Complexity</span>
          <span className={cn(
            'text-xs font-semibold px-2 py-0.5 rounded-full border capitalize',
            complexityColor[plan.estimated_complexity] ?? complexityColor.medium,
          )}>
            {plan.estimated_complexity}
          </span>
        </div>
      )}

      {/* Cost */}
      {cost?.monthly_cost !== undefined && (
        <div className="flex items-center gap-2">
          <DollarSign className="w-3.5 h-3.5 text-emerald-500" />
          <span className="text-xs text-slate-400 dark:text-slate-500">Est. monthly cost</span>
          <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
            ${Number(cost.monthly_cost).toFixed(2)}
          </span>
          {cost.cost_profile && (
            <span className="text-xs text-slate-400 dark:text-slate-500 capitalize">
              ({cost.cost_profile})
            </span>
          )}
        </div>
      )}

      {/* Required artifacts count */}
      {(plan?.required_artifacts?.length ?? 0) > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400 dark:text-slate-500">Artifacts</span>
          <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
            {plan!.required_artifacts!.length} planned
          </span>
        </div>
      )}

      {/* Plan reasoning summary */}
      {(plan?.reasoning_summary ?? plan?.summary) && (
        <p className="w-full text-xs text-slate-500 dark:text-slate-400 mt-1">
          {plan!.reasoning_summary ?? plan!.summary}
        </p>
      )}
    </div>
  )
}

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>()
  const { data: task, isLoading, error, refetch } = useTask(id!)
  const reviewTask = useReviewTask()
  const [activeTab, setActiveTab]     = useState<Tab>('pipeline')
  const [reviewError, setReviewError] = useState<string | null>(null)

  useTaskPolling(
    task && !isTerminalStatus(task.status) && task.status !== 'awaiting_human_review'
      ? id
      : undefined,
    { onComplete: () => refetch() }
  )

  if (isLoading) return <PageLoader />
  if (error)     return <div className="p-6"><ErrorAlert message={error.message} /></div>
  if (!task)     return null

  // ── Artifact resolution (multi-path, backward-compatible) ───────────────────
  const artifacts = (
    task.result?.human_review?.reviewed_artifacts ??
    task.result?.human_review?.original_artifacts ??
    task.infra?.artifacts ??
    task.result?.infrastructure?.artifacts ??
    task.result?.artifacts ??
    {}
  ) as Record<string, string>

  // CI/CD artifacts: top-level task.cicd or task.result.cicd
  const cicdArtifacts = (
    task.cicd ??
    task.result?.cicd ??
    {}
  ) as Record<string, string>

  // Terraform outputs: top-level task.terraform_outputs
  const terraformOutputs = task.terraform_outputs

  // Validation: top-level or nested
  const validation: ValidationResult | undefined =
    task.validation ?? task.result?.validation

  const diffs     = (task.result?.diffs ?? {}) as Record<string, { before: string; after: string; changes?: number }>
  const security  = task.result?.security
  const vulns     = security?.vulnerabilities ?? []

  const handleReview = async (reviewed: Record<string, string>, notes: string) => {
    setReviewError(null)
    const payload: ReviewArtifactsRequest = {
      reviewed_artifacts: reviewed,
      review_notes: notes || undefined,
    }
    try {
      await reviewTask.mutateAsync({ taskId: id!, payload })
      refetch()
    } catch (e) {
      setReviewError((e as Error).message)
    }
  }

  const isRunning       = task.status === 'in_progress' || task.status === 'pending'
  const hasArtifacts    = Object.keys({ ...artifacts, ...cicdArtifacts }).length > 0
  const hasTerraform    = !!terraformOutputs && Object.keys(terraformOutputs).length > 0
  const hasDiffs        = Object.keys(diffs).length > 0

  return (
    <div className="p-6 space-y-6 animate-slide-in">

      {/* ── Back + header ───────────────────────────────── */}
      <div className="flex items-start gap-4">
        <Link
          to="/tasks"
          className={cn(
            'mt-1 p-1.5 rounded-lg transition-colors shrink-0',
            'text-slate-400 dark:text-slate-500',
            'hover:text-slate-900 dark:hover:text-white',
            'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
          )}
        >
          <ArrowLeft className="w-4 h-4" />
        </Link>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <StatusBadge status={task.status} />
            <span className="text-xs text-slate-400 dark:text-slate-600 font-mono">{task.id}</span>
            {isRunning && (
              <button
                onClick={() => refetch()}
                className="text-slate-400 dark:text-slate-600 hover:text-slate-700 dark:hover:text-white transition-colors"
                title="Refresh"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <h1 className="text-lg font-semibold text-slate-900 dark:text-white mt-2 leading-snug">
            {task.prompt.length > 140 ? task.prompt.slice(0, 140) + '…' : task.prompt}
          </h1>
          <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
            Created {formatDate(task.created_at)}
            {task.updated_at !== task.created_at && (
              <> · Updated {formatDate(task.updated_at)}</>
            )}
          </p>
        </div>
      </div>

      {/* ── Plan / cost strip ────────────────────────────── */}
      <PlanCostStrip task={task} />

      {/* ── Error ─────────────────────────────────────────── */}
      {task.error_message && (
        <ErrorAlert title="Task failed" message={task.error_message} />
      )}

      {/* ── Human review ──────────────────────────────────── */}
      {task.status === 'awaiting_human_review' && (
        <div className="space-y-3">
          {reviewError && (
            <ErrorAlert message={reviewError} onDismiss={() => setReviewError(null)} />
          )}
          <Link
            to={`/tasks/${task.id}/review`}
            className={cn(
              'flex items-center justify-center gap-2 w-full py-3 rounded-xl text-sm font-medium transition-colors',
              'bg-emerald-600 hover:bg-emerald-500 text-white',
            )}
          >
            <FileCode className="w-4 h-4" />
            Open Review Page
          </Link>
          <ArtifactReview
            task={task}
            onSubmitReview={handleReview}
            isLoading={reviewTask.isPending}
          />
        </div>
      )}

      {/* ── Running banner ────────────────────────────────── */}
      {isRunning && (
        <div className={cn(
          'flex items-center gap-3 p-4 rounded-xl',
          'bg-brand-50 dark:bg-brand-600/10',
          'border border-brand-200 dark:border-brand-500/20',
        )}>
          <span className="w-4 h-4 border-2 border-brand-400/40 border-t-brand-500 rounded-full animate-spin shrink-0" />
          <p className="text-sm text-brand-700 dark:text-brand-300">
            Task is running — page updates automatically.
          </p>
        </div>
      )}

      {/* ── Security score compact strip ──────────────────── */}
      {security && <SecurityScore security={security} />}

      {/* ── Content tabs ──────────────────────────────────── */}
      <div>
        {/* Tab bar */}
        <div className={cn(
          'flex gap-1 mb-4 overflow-x-auto',
          'border-b border-slate-200 dark:border-white/[0.06]',
        )}>
          {TABS.map(({ key, label, icon: Icon }) => {
            // Hide tabs with no data (except pipeline + logs which are always relevant)
            const alwaysShow = key === 'pipeline' || key === 'logs'
            const hidden =
              (!alwaysShow && key === 'artifacts' && !hasArtifacts)         ||
              (key === 'terraform' && !hasTerraform)                        ||
              (key === 'security'  && !security)                            ||
              (key === 'diffs'     && !hasDiffs)

            if (hidden) return null

            const count =
              key === 'artifacts' ? Object.keys({ ...artifacts, ...cicdArtifacts }).length
              : key === 'diffs'   ? Object.keys(diffs).length
              : key === 'logs'    ? task.logs.length
              : key === 'security' && security ? vulns.length
              : 0

            return (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={cn(
                  'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 whitespace-nowrap transition-colors -mb-px',
                  activeTab === key
                    ? 'border-brand-500 text-brand-600 dark:text-white'
                    : cn(
                        'border-transparent',
                        'text-slate-500 dark:text-slate-500',
                        'hover:text-slate-700 dark:hover:text-slate-300',
                      )
                )}
              >
                <Icon className="w-4 h-4" />
                {label}
                {count > 0 && (
                  <span className={cn(
                    'px-1.5 py-0.5 rounded text-xs',
                    'bg-slate-100 dark:bg-white/[0.06]',
                    'text-slate-500 dark:text-slate-400',
                  )}>
                    {count}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        {/* ── Pipeline tab ───────────────────────────────── */}
        {activeTab === 'pipeline' && (
          <div className="space-y-4">
            <PipelineVisualizer logs={task.logs} taskStatus={task.status} />

            {/* Validation status beneath pipeline when available */}
            {validation && <ValidationPanel validation={validation} />}
          </div>
        )}

        {/* ── Artifacts tab ──────────────────────────────── */}
        {activeTab === 'artifacts' && hasArtifacts && (
          <ArtifactTabs artifacts={artifacts} cicdArtifacts={cicdArtifacts} />
        )}

        {/* ── Terraform / Infra tab ──────────────────────── */}
        {activeTab === 'terraform' && hasTerraform && (
          <TerraformOutputsPanel outputs={terraformOutputs!} />
        )}

        {/* ── Security tab ───────────────────────────────── */}
        {activeTab === 'security' && security && (
          <div className="space-y-6">
            {validation && <ValidationPanel validation={validation} />}

            {vulns.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-slate-600 dark:text-slate-400 mb-3">
                  Vulnerabilities ({vulns.length})
                </h3>
                <VulnerabilityList vulnerabilities={vulns} />
              </div>
            )}

            {security.recommendations && security.recommendations.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-slate-600 dark:text-slate-400 mb-3">
                  Recommendations
                </h3>
                <div className="space-y-2">
                  {security.recommendations.map((r, i) => (
                    <div
                      key={i}
                      className={cn(
                        'flex items-start gap-3 p-3 rounded-lg',
                        'bg-white dark:bg-surface-800/40',
                        'border border-slate-100 dark:border-white/[0.04]',
                      )}
                    >
                      <AlertCircle className="w-4 h-4 text-brand-500 dark:text-brand-400 shrink-0 mt-0.5" />
                      <p className="text-sm text-slate-700 dark:text-slate-300">{r}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {security.env_security && (
              <div>
                <h3 className="text-sm font-medium text-slate-600 dark:text-slate-400 mb-3">
                  Environment Security
                </h3>
                <div className={cn(
                  'p-4 rounded-xl space-y-2',
                  'bg-white dark:bg-surface-800/40',
                  'border border-slate-200 dark:border-white/[0.06]',
                )}>
                  {security.env_security.score !== undefined && (
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-slate-500 dark:text-slate-400">Env score</span>
                      <span className="font-semibold text-slate-900 dark:text-white">
                        {security.env_security.score}/100
                      </span>
                    </div>
                  )}
                  {security.env_security.exposed_secrets?.map((s, i) => (
                    <div
                      key={i}
                      className={cn(
                        'text-xs px-3 py-1.5 rounded border',
                        'text-red-600 dark:text-red-300',
                        'bg-red-50 dark:bg-red-500/10',
                        'border-red-200 dark:border-red-500/20',
                      )}
                    >
                      🔑 Exposed: {s}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Diffs tab ──────────────────────────────────── */}
        {activeTab === 'diffs' && hasDiffs && (
          <DiffViewer diffs={diffs} />
        )}

        {/* ── Logs tab ───────────────────────────────────── */}
        {activeTab === 'logs' && (
          <LogViewer logs={task.logs} className="max-h-[40rem] overflow-y-auto" />
        )}
      </div>
    </div>
  )
}
