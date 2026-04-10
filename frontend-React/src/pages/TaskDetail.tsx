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
import { SecurityScore } from '@/components/security/SecurityScore'
import { VulnerabilityList } from '@/components/security/VulnerabilityList'
import { formatDate, isTerminalStatus } from '@/lib/utils'
import type { ReviewArtifactsRequest } from '@/types'
import { useQueryClient } from '@tanstack/react-query'
import { TASKS_KEY } from '@/hooks/useTasks'

type Tab = 'artifacts' | 'security' | 'diffs' | 'logs'

const TABS: { key: Tab; label: string; icon: React.ElementType }[] = [
  { key: 'artifacts', label: 'Artifacts',  icon: FileCode  },
  { key: 'security',  label: 'Security',   icon: Shield    },
  { key: 'diffs',     label: 'Diffs',      icon: GitMerge  },
  { key: 'logs',      label: 'Logs',       icon: Terminal  },
]

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>()
  const qc = useQueryClient()
  const { data: task, isLoading, error, refetch } = useTask(id!)
  const reviewTask = useReviewTask()
  const [activeTab, setActiveTab] = useState<Tab>('artifacts')
  const [reviewError, setReviewError] = useState<string | null>(null)

  // Poll while non-terminal
  useTaskPolling(
    task && !isTerminalStatus(task.status) && task.status !== 'awaiting_human_review'
      ? id
      : undefined,
    { onComplete: () => refetch() }
  )

  if (isLoading) return <PageLoader />
  if (error)     return (
    <div className="p-6">
      <ErrorAlert message={error.message} />
    </div>
  )
  if (!task)     return null

  const artifacts = (task.result?.artifacts ?? {}) as Record<string, string>
  const diffs     = (task.result?.diffs     ?? {}) as Record<string, { before: string; after: string; changes?: number }>
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

  const isRunning = task.status === 'in_progress' || task.status === 'pending'

  return (
    <div className="p-6 space-y-6 animate-slide-in">
      {/* Back + header */}
      <div className="flex items-start gap-4">
        <Link
          to="/tasks"
          className="mt-1 p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-white/[0.05] transition-colors shrink-0"
        >
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <StatusBadge status={task.status} />
            <span className="text-xs text-slate-600 font-mono">{task.id}</span>
            {isRunning && (
              <button
                onClick={() => refetch()}
                className="text-slate-600 hover:text-white transition-colors"
                title="Refresh"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <h1 className="text-lg font-semibold text-white mt-2 leading-snug">
            {task.prompt.length > 140 ? task.prompt.slice(0, 140) + '…' : task.prompt}
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Created {formatDate(task.created_at)}
            {task.updated_at !== task.created_at && (
              <> · Updated {formatDate(task.updated_at)}</>
            )}
          </p>
        </div>
      </div>

      {/* Plan summary */}
      {task.plan?.summary && (
        <div className="p-4 rounded-xl bg-surface-800/40 border border-white/[0.06]">
          <p className="text-xs font-medium text-slate-500 mb-1">Plan summary</p>
          <p className="text-sm text-slate-300">{task.plan.summary}</p>
        </div>
      )}

      {/* Error message */}
      {task.error_message && (
        <ErrorAlert title="Task failed" message={task.error_message} />
      )}

      {/* Human review UI */}
      {task.status === 'awaiting_human_review' && (
        <div className="space-y-3">
          {reviewError && <ErrorAlert message={reviewError} onDismiss={() => setReviewError(null)} />}
          <ArtifactReview
            task={task}
            onSubmitReview={handleReview}
            isLoading={reviewTask.isPending}
          />
        </div>
      )}

      {/* Running indicator */}
      {isRunning && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-brand-600/10 border border-brand-500/20">
          <span className="w-4 h-4 border-2 border-brand-400/30 border-t-brand-400 rounded-full animate-spin shrink-0" />
          <p className="text-sm text-brand-300">
            Task is running — page updates automatically.
          </p>
        </div>
      )}

      {/* Security score (compact, always visible when available) */}
      {security && (
        <SecurityScore security={security} />
      )}

      {/* Tabs */}
      {(Object.keys(artifacts).length > 0 ||
        Object.keys(diffs).length > 0 ||
        task.logs.length > 0 ||
        security) && (
        <div>
          {/* Tab bar */}
          <div className="flex gap-1 border-b border-white/[0.06] mb-4">
            {TABS.map(({ key, label, icon: Icon }) => {
              const count =
                key === 'artifacts' ? Object.keys(artifacts).length
                : key === 'diffs'   ? Object.keys(diffs).length
                : key === 'logs'    ? task.logs.length
                : key === 'security' && security ? vulns.length
                : 0
              const hidden =
                (key === 'artifacts' && !Object.keys(artifacts).length) ||
                (key === 'diffs'     && !Object.keys(diffs).length) ||
                (key === 'security'  && !security)

              if (hidden) return null

              return (
                <button
                  key={key}
                  onClick={() => setActiveTab(key)}
                  className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
                    activeTab === key
                      ? 'border-brand-500 text-white'
                      : 'border-transparent text-slate-500 hover:text-slate-300'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {label}
                  {count > 0 && (
                    <span className="px-1.5 py-0.5 rounded text-xs bg-white/[0.06] text-slate-400">
                      {count}
                    </span>
                  )}
                </button>
              )
            })}
          </div>

          {/* Tab content */}
          {activeTab === 'artifacts' && Object.keys(artifacts).length > 0 && (
            <ArtifactTabs artifacts={artifacts} />
          )}

          {activeTab === 'security' && security && (
            <div className="space-y-6">
              {vulns.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-3">
                    Vulnerabilities ({vulns.length})
                  </h3>
                  <VulnerabilityList vulnerabilities={vulns} />
                </div>
              )}
              {security.recommendations && security.recommendations.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-3">Recommendations</h3>
                  <div className="space-y-2">
                    {security.recommendations.map((r, i) => (
                      <div
                        key={i}
                        className="flex items-start gap-3 p-3 rounded-lg bg-surface-800/40 border border-white/[0.04]"
                      >
                        <AlertCircle className="w-4 h-4 text-brand-400 shrink-0 mt-0.5" />
                        <p className="text-sm text-slate-300">{r}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {security.env_security && (
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-3">Environment Security</h3>
                  <div className="p-4 rounded-xl bg-surface-800/40 border border-white/[0.06] space-y-2">
                    {security.env_security.score !== undefined && (
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-slate-400">Env score</span>
                        <span className="font-semibold text-white">
                          {security.env_security.score}/100
                        </span>
                      </div>
                    )}
                    {security.env_security.exposed_secrets?.map((s, i) => (
                      <div
                        key={i}
                        className="text-xs text-red-300 bg-red-500/10 px-3 py-1.5 rounded border border-red-500/20"
                      >
                        🔑 Exposed: {s}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'diffs' && Object.keys(diffs).length > 0 && (
            <DiffViewer diffs={diffs} />
          )}

          {activeTab === 'logs' && (
            <LogViewer logs={task.logs} className="h-96" />
          )}
        </div>
      )}
    </div>
  )
}
