import { useState } from 'react'
import {
  CheckCircle2,
  XCircle,
  PenLine,
  Send,
  Loader2,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  ThumbsUp,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PlanValidationDecision } from '@/types'

interface Props {
  onDecision: (decision: PlanValidationDecision, feedback?: string) => Promise<void>
  isLoading: boolean
  rejectedMessage?: string | null
  className?: string
}

type PanelState = 'idle' | 'modifying' | 'rejected' | 'approved'

export function ValidationPanel({ onDecision, isLoading, rejectedMessage, className }: Props) {
  const [panelState, setPanelState] = useState<PanelState>('idle')
  const [feedback, setFeedback] = useState('')
  const [feedbackError, setFeedbackError] = useState('')
  const [showModify, setShowModify] = useState(false)

  const handleApprove = async () => {
    await onDecision('approved')
    setPanelState('approved')
  }

  const handleReject = async () => {
    await onDecision('rejected')
    setPanelState('rejected')
  }

  const handleSubmitChanges = async () => {
    if (!feedback.trim()) {
      setFeedbackError('Please describe the changes you want.')
      return
    }
    setFeedbackError('')
    await onDecision('modified', feedback.trim())
    setFeedback('')
    setShowModify(false)
    setPanelState('idle')
  }

  // If the parent passes a rejectedMessage it means the rejection is confirmed
  if (rejectedMessage) {
    return (
      <div className={cn(
        'flex flex-col items-center gap-4 py-8 px-6 rounded-xl text-center',
        'bg-red-50 dark:bg-red-500/5',
        'border border-red-200 dark:border-red-500/20',
        className
      )}>
        <div className="w-12 h-12 rounded-full flex items-center justify-center bg-red-100 dark:bg-red-500/15">
          <XCircle className="w-6 h-6 text-red-500 dark:text-red-400" />
        </div>
        <div>
          <p className="text-base font-semibold text-red-700 dark:text-red-300">Plan Rejected</p>
          <p className="text-sm text-red-500 dark:text-red-400 mt-1">{rejectedMessage}</p>
        </div>
      </div>
    )
  }

  return (
    <div className={cn('space-y-4', className)}>

      {/* ── Separator ─────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <div className="flex-1 h-px bg-slate-200 dark:bg-white/[0.06]" />
        <span className="text-xs font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider">
          Review decision
        </span>
        <div className="flex-1 h-px bg-slate-200 dark:bg-white/[0.06]" />
      </div>

      {/* ── Action buttons row ────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row gap-3">

        {/* Approve */}
        <button
          onClick={handleApprove}
          disabled={isLoading}
          className={cn(
            'group flex-1 flex items-center justify-center gap-2.5 px-5 py-3 rounded-xl',
            'text-sm font-semibold transition-all duration-200',
            'bg-emerald-600 hover:bg-emerald-500 active:scale-[0.98]',
            'text-white shadow-sm hover:shadow-emerald-500/25 hover:shadow-md',
            'disabled:opacity-50 disabled:cursor-not-allowed disabled:scale-100 disabled:shadow-none',
            'border border-emerald-600 hover:border-emerald-500'
          )}
        >
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <CheckCircle2 className="w-4 h-4 transition-transform group-hover:scale-110" />
          )}
          {isLoading ? 'Processing…' : 'Approve Plan'}
        </button>

        {/* Request Changes */}
        <button
          onClick={() => setShowModify((v) => !v)}
          disabled={isLoading}
          className={cn(
            'group flex-1 flex items-center justify-center gap-2.5 px-5 py-3 rounded-xl',
            'text-sm font-semibold transition-all duration-200 active:scale-[0.98]',
            showModify
              ? 'bg-amber-50 dark:bg-amber-500/10 border-amber-300 dark:border-amber-500/40 text-amber-700 dark:text-amber-300'
              : cn(
                  'border border-slate-200 dark:border-white/[0.10]',
                  'bg-white dark:bg-surface-800/60',
                  'text-slate-600 dark:text-slate-300',
                  'hover:border-amber-300 dark:hover:border-amber-500/40',
                  'hover:bg-amber-50 dark:hover:bg-amber-500/10',
                  'hover:text-amber-700 dark:hover:text-amber-300'
                ),
            'disabled:opacity-50 disabled:cursor-not-allowed disabled:scale-100'
          )}
        >
          <PenLine className="w-4 h-4 transition-transform group-hover:scale-110" />
          Request Changes
          {showModify
            ? <ChevronUp className="w-3.5 h-3.5 ml-auto opacity-60" />
            : <ChevronDown className="w-3.5 h-3.5 ml-auto opacity-60" />}
        </button>

        {/* Reject */}
        <button
          onClick={handleReject}
          disabled={isLoading}
          className={cn(
            'group sm:w-auto flex items-center justify-center gap-2.5 px-5 py-3 rounded-xl',
            'text-sm font-semibold transition-all duration-200 active:scale-[0.98]',
            'border border-red-200 dark:border-red-500/30',
            'bg-red-50 dark:bg-red-500/5',
            'text-red-600 dark:text-red-400',
            'hover:bg-red-100 dark:hover:bg-red-500/10',
            'hover:border-red-300 dark:hover:border-red-500/50',
            'disabled:opacity-50 disabled:cursor-not-allowed disabled:scale-100'
          )}
        >
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <XCircle className="w-4 h-4 transition-transform group-hover:scale-110" />
          )}
          Reject
        </button>
      </div>

      {/* ── Modify panel (animated expand) ───────────────────────────── */}
      <div
        className={cn(
          'overflow-hidden transition-all duration-300 ease-in-out',
          showModify ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'
        )}
      >
        <div className={cn(
          'rounded-xl border p-4 space-y-3',
          'bg-amber-50/60 dark:bg-amber-500/5',
          'border-amber-200 dark:border-amber-500/25'
        )}>
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-500 dark:text-amber-400 shrink-0" />
            <p className="text-sm font-medium text-amber-700 dark:text-amber-300">
              Describe what you want to change
            </p>
          </div>

          <textarea
            value={feedback}
            onChange={(e) => {
              setFeedback(e.target.value)
              if (e.target.value.trim()) setFeedbackError('')
            }}
            placeholder="e.g. Use Helm charts instead of raw Kubernetes manifests. Add an ArgoCD deployment step. Remove Docker Compose since we use Kubernetes only…"
            rows={4}
            disabled={isLoading}
            className={cn(
              'w-full rounded-lg text-sm px-3.5 py-2.5 resize-none',
              'bg-white dark:bg-surface-800/60',
              'text-slate-800 dark:text-slate-200',
              'placeholder-slate-400 dark:placeholder-slate-600',
              'focus:outline-none transition-colors',
              feedbackError
                ? 'border border-red-300 dark:border-red-500/40 focus:border-red-400 dark:focus:border-red-500/60'
                : 'border border-amber-200 dark:border-amber-500/30 focus:border-amber-400 dark:focus:border-amber-500/60',
              'disabled:opacity-60 disabled:cursor-not-allowed'
            )}
          />

          {feedbackError && (
            <p className="text-xs text-red-500 dark:text-red-400">{feedbackError}</p>
          )}

          <div className="flex items-center justify-between">
            <span className="text-xs text-amber-600/70 dark:text-amber-400/60">
              {feedback.length}/2000 characters
            </span>
            <button
              onClick={handleSubmitChanges}
              disabled={isLoading || !feedback.trim()}
              className={cn(
                'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200',
                'bg-amber-500 hover:bg-amber-400 text-white',
                'shadow-sm hover:shadow-amber-400/30 hover:shadow-md',
                'active:scale-[0.98]',
                'disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none disabled:scale-100'
              )}
            >
              {isLoading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Send className="w-3.5 h-3.5" />
              )}
              Submit Changes
            </button>
          </div>
        </div>
      </div>

      {/* ── Approved inline confirmation ───────────────────────────────── */}
      {panelState === 'approved' && !isLoading && (
        <div className={cn(
          'flex items-center gap-3 px-4 py-3 rounded-xl animate-slide-in',
          'bg-emerald-50 dark:bg-emerald-500/10',
          'border border-emerald-200 dark:border-emerald-500/30'
        )}>
          <ThumbsUp className="w-4 h-4 text-emerald-500 dark:text-emerald-400 shrink-0" />
          <p className="text-sm font-medium text-emerald-700 dark:text-emerald-300">
            Plan approved — continuing execution…
          </p>
        </div>
      )}
    </div>
  )
}
