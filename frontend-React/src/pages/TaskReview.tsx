import { useParams, Link, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import {
  ArrowLeft,
  CheckCircle,
  Edit3,
  FileCode,
  AlertTriangle,
  Calendar,
  Hash,
  Download,
} from 'lucide-react'
import { useTask, useReviewTask } from '@/hooks/useTasks'
import { PageLoader } from '@/components/common/LoadingSpinner'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { StatusBadge } from '@/components/common/StatusBadge'
import { CodeViewer } from '@/components/artifacts/CodeViewer'
import { ValidationIssues } from '@/components/artifacts/ValidationIssues'
import { SecurityScore } from '@/components/security/SecurityScore'
import { detectLang, formatDate, cn } from '@/lib/utils'
import type { ReviewArtifactsRequest } from '@/types'

function downloadFile(name: string, content: string) {
  const blob = new Blob([content], { type: 'text/plain' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href = url; a.download = name; a.click()
  URL.revokeObjectURL(url)
}

export default function TaskReview() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: task, isLoading, error } = useTask(id!)
  const reviewTask = useReviewTask()

  const [activeFile, setActiveFile] = useState<string>('')
  const [editMode, setEditMode]     = useState(false)
  const [editedArtifacts, setEditedArtifacts] = useState<Record<string, string> | null>(null)
  const [notes, setNotes]           = useState('')
  const [reviewError, setReviewError] = useState<string | null>(null)

  if (isLoading) return <PageLoader />
  if (error)     return <div className="p-6"><ErrorAlert message={error.message} /></div>
  if (!task)     return null

  // Resolve artifacts from the correct nested path
  const rawArtifacts: Record<string, string> =
    task.result?.human_review?.original_artifacts ??
    task.result?.infrastructure?.artifacts ??
    (task.result?.artifacts as Record<string, string> | undefined) ??
    {}

  // Working copy — allows in-place edits without mutating the original
  const artifacts = editedArtifacts ?? rawArtifacts

  const fileNames = Object.keys(artifacts)
  const currentFile = activeFile || fileNames[0] || ''
  const validation  = task.result?.validation
  const security    = task.result?.security

  const setArtifact = (name: string, content: string) => {
    setEditedArtifacts((prev) => ({ ...(prev ?? rawArtifacts), [name]: content }))
  }

  const handleApprove = async () => {
    setReviewError(null)
    const payload: ReviewArtifactsRequest = {
      reviewed_artifacts: artifacts,
      review_notes: notes || undefined,
    }
    try {
      await reviewTask.mutateAsync({ taskId: id!, payload })
      navigate(`/tasks/${id}`)
    } catch (e) {
      setReviewError((e as Error).message)
    }
  }

  const hasNoArtifacts = fileNames.length === 0

  return (
    <div className="p-6 space-y-6 animate-slide-in">

      {/* ── Header ──────────────────────────────────────────── */}
      <div className="flex items-start gap-4">
        <Link
          to={`/tasks/${id}`}
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
          <div className="flex items-center gap-3 flex-wrap mb-2">
            <StatusBadge status={task.status} />
            <span className="text-xs font-mono text-slate-400 dark:text-slate-600">{task.id}</span>
          </div>
          <h1 className="text-lg font-semibold text-slate-900 dark:text-white leading-snug">
            Human Review
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-2">
            {task.prompt}
          </p>
          <div className="flex items-center gap-4 mt-2 text-xs text-slate-400 dark:text-slate-500">
            <span className="flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              {formatDate(task.created_at)}
            </span>
            <span className="flex items-center gap-1">
              <Hash className="w-3 h-3" />
              {fileNames.length} artifact{fileNames.length !== 1 ? 's' : ''}
            </span>
          </div>
        </div>
      </div>

      {/* ── Review banner ───────────────────────────────────── */}
      <div className={cn(
        'flex items-start gap-3 p-4 rounded-xl',
        'bg-amber-50 dark:bg-amber-500/10',
        'border border-amber-200 dark:border-amber-500/20',
      )}>
        <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-medium text-amber-700 dark:text-amber-300">
            Human review required
          </p>
          <p className="text-xs text-amber-600/80 dark:text-amber-400/60 mt-0.5">
            Review and optionally edit the generated artifacts. Click <strong>Approve & Finalize</strong> when done.
          </p>
        </div>
      </div>

      {reviewError && (
        <ErrorAlert message={reviewError} onDismiss={() => setReviewError(null)} />
      )}

      {hasNoArtifacts ? (
        <div className={cn(
          'p-6 rounded-xl text-center',
          'bg-white dark:bg-surface-800/40',
          'border border-slate-200 dark:border-white/[0.06]',
        )}>
          <FileCode className="w-10 h-10 text-slate-300 dark:text-slate-600 mx-auto mb-3" />
          <p className="text-sm text-slate-500 dark:text-slate-400">
            No artifacts found for this task.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6 items-start">

          {/* ── Left sidebar ──────────────────────────────────── */}
          <div className="space-y-4">
            {/* File list */}
            <div className={cn(
              'rounded-xl overflow-hidden',
              'bg-white dark:bg-surface-800/40',
              'border border-slate-200 dark:border-white/[0.06]',
            )}>
              <div className={cn(
                'px-3 py-2.5 border-b',
                'bg-slate-50 dark:bg-surface-800/60',
                'border-slate-100 dark:border-white/[0.05]',
              )}>
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                  Generated files
                </span>
              </div>
              <ul className="py-1">
                {fileNames.map((name) => {
                  const isActive = name === currentFile
                  const isEdited = editedArtifacts && editedArtifacts[name] !== rawArtifacts[name]
                  return (
                    <li key={name}>
                      <button
                        onClick={() => { setActiveFile(name); setEditMode(false) }}
                        className={cn(
                          'w-full flex items-center gap-2.5 px-3 py-2 text-left transition-colors',
                          isActive
                            ? 'bg-brand-50 dark:bg-brand-600/15 text-brand-700 dark:text-brand-300'
                            : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-white/[0.03]',
                        )}
                      >
                        <FileCode className="w-3.5 h-3.5 shrink-0" />
                        <span className="text-xs font-mono truncate flex-1">{name}</span>
                        {isEdited && (
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" title="Modified" />
                        )}
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>

            {/* Validation issues */}
            {validation && (
              <div className={cn(
                'rounded-xl overflow-hidden',
                'bg-white dark:bg-surface-800/40',
                'border border-slate-200 dark:border-white/[0.06]',
              )}>
                <div className={cn(
                  'px-3 py-2.5 border-b',
                  'bg-slate-50 dark:bg-surface-800/60',
                  'border-slate-100 dark:border-white/[0.05]',
                )}>
                  <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                    Validation
                  </span>
                </div>
                <div className="p-3">
                  <ValidationIssues validation={validation} />
                </div>
              </div>
            )}

            {/* Security score */}
            {security && <SecurityScore security={security} compact />}
          </div>

          {/* ── Main code area ──────────────────────────────── */}
          <div className="space-y-4">
            {currentFile && (
              <div className={cn(
                'rounded-xl overflow-hidden',
                'bg-white dark:bg-surface-900',
                'border border-slate-200 dark:border-white/[0.06]',
              )}>
                {/* File header */}
                <div className={cn(
                  'flex items-center justify-between px-4 py-2.5',
                  'bg-slate-50 dark:bg-surface-800/50',
                  'border-b border-slate-100 dark:border-white/[0.05]',
                )}>
                  <span className="text-xs font-mono text-slate-600 dark:text-slate-300 font-medium">
                    {currentFile}
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => downloadFile(currentFile, artifacts[currentFile])}
                      className="flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500 hover:text-slate-700 dark:hover:text-white transition-colors"
                    >
                      <Download className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => setEditMode((v) => !v)}
                      className={cn(
                        'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs border transition-colors',
                        editMode
                          ? 'bg-brand-50 dark:bg-brand-600/20 border-brand-200 dark:border-brand-500/30 text-brand-700 dark:text-brand-300'
                          : 'border-slate-200 dark:border-white/[0.08] text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-white',
                      )}
                    >
                      <Edit3 className="w-3 h-3" />
                      {editMode ? 'Preview' : 'Edit'}
                    </button>
                  </div>
                </div>

                {editMode ? (
                  <textarea
                    value={artifacts[currentFile]}
                    onChange={(e) => setArtifact(currentFile, e.target.value)}
                    className={cn(
                      'w-full font-mono text-xs p-4 resize-none focus:outline-none',
                      'bg-white dark:bg-surface-950',
                      'text-slate-800 dark:text-slate-200',
                    )}
                    style={{ minHeight: '500px' }}
                    spellCheck={false}
                  />
                ) : (
                  <CodeViewer
                    code={artifacts[currentFile]}
                    language={detectLang(currentFile)}
                    showLineNumbers
                    maxHeight="500px"
                  />
                )}
              </div>
            )}

            {/* Review notes + actions */}
            <div className={cn(
              'p-4 rounded-xl space-y-4',
              'bg-white dark:bg-surface-800/40',
              'border border-slate-200 dark:border-white/[0.06]',
            )}>
              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
                  Review notes{' '}
                  <span className="text-slate-400 dark:text-slate-600">(optional)</span>
                </label>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Add any notes or feedback for the AI agents…"
                  rows={3}
                  className={cn(
                    'w-full rounded-lg px-3 py-2 text-sm resize-none focus:outline-none transition-colors',
                    'bg-slate-50 dark:bg-surface-800/50',
                    'border border-slate-200 dark:border-white/[0.06]',
                    'text-slate-800 dark:text-slate-300',
                    'placeholder-slate-400 dark:placeholder-slate-600',
                    'focus:border-brand-400 dark:focus:border-brand-500/40',
                  )}
                />
              </div>

              <div className="flex items-center gap-3">
                <Link
                  to={`/tasks/${id}`}
                  className={cn(
                    'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                    'border border-slate-200 dark:border-white/[0.08]',
                    'text-slate-600 dark:text-slate-400',
                    'hover:text-slate-900 dark:hover:text-white',
                    'hover:border-slate-300 dark:hover:border-white/20',
                  )}
                >
                  Cancel
                </Link>
                <button
                  onClick={handleApprove}
                  disabled={reviewTask.isPending}
                  className="flex items-center gap-2 px-6 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {reviewTask.isPending ? (
                    <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  ) : (
                    <CheckCircle className="w-4 h-4" />
                  )}
                  Approve & Finalize
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
