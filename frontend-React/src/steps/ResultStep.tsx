import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  CheckCircle2,
  Download,
  ExternalLink,
  FileText,
  RefreshCw,
  Loader2,
  AlertCircle,
  RotateCcw,
} from 'lucide-react'
import { StepContainer } from '@/components/workflow/StepContainer'
import { LogViewer } from '@/components/workflow/LogViewer'
import { useWorkflowStore } from '@/store/workflowStore'
import {
  downloadAllArtifacts,
  downloadFile,
  displayName,
  getInfraArtifacts,
  getTerraformArtifacts,
  getKubernetesArtifacts,
  getCicdArtifacts,
  submitReview,
} from '@/services/workflowApi'
import { cn } from '@/lib/utils'
import type { TaskResponse } from '@/types'

// ── Artifact download list ────────────────────────────────────────────────────

function ArtifactDownloadList({
  task,
  editedArtifacts,
}: {
  task: TaskResponse
  editedArtifacts: Record<string, string>
}) {
  const sections: Array<{ label: string; color: string; keys: string[] }> = [
    { label: 'Infrastructure', color: 'text-cyan-600 dark:text-cyan-400',    keys: Object.keys(getInfraArtifacts(task))        },
    { label: 'Terraform',      color: 'text-orange-600 dark:text-orange-400', keys: Object.keys(getTerraformArtifacts(task))    },
    { label: 'Kubernetes',     color: 'text-blue-600 dark:text-blue-400',     keys: Object.keys(getKubernetesArtifacts(task))   },
    { label: 'CI/CD',          color: 'text-purple-600 dark:text-purple-400', keys: Object.keys(getCicdArtifacts(task))         },
  ].filter((s) => s.keys.length > 0)

  const allArtifacts = {
    ...getInfraArtifacts(task),
    ...getTerraformArtifacts(task),
    ...getKubernetesArtifacts(task),
    ...getCicdArtifacts(task),
  }

  return (
    <div className={cn(
      'rounded-xl border overflow-hidden',
      'border-slate-200 dark:border-white/[0.06]',
      'bg-white dark:bg-surface-900',
    )}>
      <div className={cn(
        'flex items-center justify-between px-4 py-3',
        'border-b border-slate-200 dark:border-white/[0.06]',
        'bg-slate-50 dark:bg-surface-800/40',
      )}>
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-slate-400" />
          <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
            {Object.keys(allArtifacts).length} artifacts generated
          </span>
        </div>
        <button
          onClick={() => downloadAllArtifacts(task, editedArtifacts)}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
            'bg-brand-600 hover:bg-brand-500 text-white',
          )}
        >
          <Download className="w-3.5 h-3.5" />
          Download All
        </button>
      </div>

      <div className="divide-y divide-slate-100 dark:divide-white/[0.04]">
        {sections.map(({ label, color, keys }) => (
          <div key={label} className="px-4 py-3">
            <p className={cn('text-xs font-semibold uppercase tracking-wider mb-2', color)}>{label}</p>
            <div className="space-y-1.5">
              {keys.map((k) => {
                const content = editedArtifacts[k] ?? allArtifacts[k] ?? ''
                const isEdited = Boolean(editedArtifacts[k])
                return (
                  <div key={k} className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-xs font-mono text-slate-600 dark:text-slate-400 truncate">
                        {displayName(k)}
                      </span>
                      {isEdited && (
                        <span className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-500/30">
                          edited
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => downloadFile(displayName(k), content)}
                      className="shrink-0 flex items-center gap-1 px-2 py-1 rounded text-xs text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-white/[0.05] transition-colors"
                    >
                      <Download className="w-3 h-3" />
                      .dl
                    </button>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Submit review banner ──────────────────────────────────────────────────────

function ReviewSubmitBanner({
  editCount,
  taskId,
  onSuccess,
}: {
  editCount: number
  taskId: string
  onSuccess: () => void
}) {
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted]   = useState(false)
  const [error, setError]           = useState<string | null>(null)
  const { editedArtifacts } = useWorkflowStore()

  const handleSubmit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      await submitReview(taskId, editedArtifacts, 'Reviewed via workflow UI')
      setSubmitted(true)
      onSuccess()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  if (submitted) {
    return (
      <div className={cn(
        'flex items-center gap-3 px-4 py-3 rounded-xl',
        'bg-emerald-50 dark:bg-emerald-500/10',
        'border border-emerald-200 dark:border-emerald-500/20',
      )}>
        <CheckCircle2 className="w-4 h-4 text-emerald-500" />
        <p className="text-sm font-medium text-emerald-700 dark:text-emerald-300">
          Review submitted — edited artifacts saved successfully.
        </p>
      </div>
    )
  }

  return (
    <div className={cn(
      'rounded-xl border p-4 space-y-3',
      'bg-amber-50 dark:bg-amber-500/10',
      'border-amber-200 dark:border-amber-500/20',
    )}>
      <div className="flex items-start gap-3">
        <RefreshCw className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-amber-800 dark:text-amber-200">
            {editCount} artifact{editCount > 1 ? 's' : ''} edited
          </p>
          <p className="text-xs text-amber-700/70 dark:text-amber-400/60 mt-0.5">
            Submit your changes to persist them on the backend.
          </p>
        </div>
      </div>
      {error && (
        <div className="flex items-center gap-2 text-xs text-red-600 dark:text-red-400">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          {error}
        </div>
      )}
      <button
        onClick={handleSubmit}
        disabled={submitting}
        className="flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium transition-colors disabled:opacity-40"
      >
        {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
        Submit Review
      </button>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

interface Props {
  onReset: () => void
}

export function ResultStep({ onReset }: Props) {
  const navigate = useNavigate()
  const { task, logs, editedArtifacts } = useWorkflowStore()
  const [reviewDone, setReviewDone] = useState(false)

  const taskLogs  = [...logs, ...(task?.logs ?? [])]
  const editCount = Object.keys(editedArtifacts).length

  return (
    <StepContainer hideActions>
      <div className="max-w-3xl space-y-6">

        {/* Success header */}
        <div className={cn(
          'flex items-start gap-4 px-5 py-4 rounded-xl',
          'bg-gradient-to-r from-emerald-50 to-brand-50 dark:from-emerald-500/10 dark:to-brand-600/10',
          'border border-emerald-200 dark:border-emerald-500/20',
        )}>
          <CheckCircle2 className="w-6 h-6 text-emerald-500 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-base font-semibold text-emerald-800 dark:text-emerald-200">
              Pipeline Complete
            </p>
            <p className="text-xs text-emerald-700/70 dark:text-emerald-400/60 mt-1">
              All agents finished successfully. Review your artifacts below and download as needed.
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {task?.id && (
              <button
                onClick={() => navigate(`/tasks/${task.id}`)}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                  'border border-emerald-200 dark:border-emerald-500/30',
                  'text-emerald-700 dark:text-emerald-300',
                  'hover:bg-emerald-100 dark:hover:bg-emerald-500/20',
                )}
              >
                <ExternalLink className="w-3.5 h-3.5" />
                Full Detail
              </button>
            )}
            <button
              onClick={onReset}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                'bg-white dark:bg-surface-800 border border-slate-200 dark:border-white/[0.08]',
                'text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-white/[0.05]',
              )}
            >
              <RotateCcw className="w-3.5 h-3.5" />
              New Task
            </button>
          </div>
        </div>

        {/* Submit review (only if there are edits) */}
        {editCount > 0 && !reviewDone && task?.id && (
          <ReviewSubmitBanner
            editCount={editCount}
            taskId={task.id}
            onSuccess={() => setReviewDone(true)}
          />
        )}

        {/* Artifact downloads */}
        {task && (
          <ArtifactDownloadList task={task} editedArtifacts={editedArtifacts} />
        )}

        {/* Logs */}
        {taskLogs.length > 0 && (
          <div>
            <p className="text-xs font-medium text-slate-400 dark:text-slate-600 uppercase tracking-wider mb-3">
              Pipeline Logs
            </p>
            <LogViewer logs={taskLogs} className="max-h-[28rem] overflow-y-auto" autoScroll={false} />
          </div>
        )}
      </div>
    </StepContainer>
  )
}
