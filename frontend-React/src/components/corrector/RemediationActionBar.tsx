import { RefreshCw, Loader2, RotateCcw, ArrowLeft, XCircle, Wand2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  canRetry: boolean
  isRetrying: boolean
  isReanalyzing: boolean
  executionFailed: boolean
  onApproveRetry: () => void
  onApplyAiPatchRetry?: () => void
  onResetOriginal?: () => void
  onReanalyze: () => void
  onBackToInfra: () => void
  onStopWorkflow: () => void
}

export function RemediationActionBar({
  canRetry,
  isRetrying,
  isReanalyzing,
  executionFailed,
  onApproveRetry,
  onApplyAiPatchRetry,
  onResetOriginal,
  onReanalyze,
  onBackToInfra,
  onStopWorkflow,
}: Props) {
  const busy = isRetrying || isReanalyzing

  return (
    <div className={cn(
      'sticky bottom-0 rounded-xl border overflow-hidden',
      'bg-[#0d1117]/95 backdrop-blur border-slate-700/60',
    )}>
      {executionFailed && (
        <div className="flex items-center gap-2 px-5 py-2.5 bg-red-500/10 border-b border-red-500/20">
          <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
          <p className="text-xs text-red-300">
            Retry attempts are exhausted. Inspect and save artifacts before restarting from infrastructure.
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={onBackToInfra}
            disabled={busy}
            className={cn(
              'flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors',
              'border border-slate-600 text-slate-400 hover:border-slate-500 hover:text-slate-200 hover:bg-slate-800/60',
              'disabled:opacity-40 disabled:cursor-not-allowed',
            )}
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Infra
          </button>

          <button
            onClick={onStopWorkflow}
            disabled={busy}
            className={cn(
              'flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors',
              'border border-red-500/30 text-red-400 hover:bg-red-500/10 hover:border-red-500/50',
              'disabled:opacity-40 disabled:cursor-not-allowed',
            )}
          >
            <XCircle className="w-4 h-4" />
            Stop Workflow
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={onResetOriginal}
            disabled={busy || !onResetOriginal}
            className={cn(
              'flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors',
              'border border-slate-600 text-slate-400 hover:bg-slate-800 hover:border-slate-500',
              'disabled:opacity-40 disabled:cursor-not-allowed',
            )}
          >
            <RotateCcw className="w-4 h-4" />
            Reset To Original
          </button>

          <button
            onClick={onReanalyze}
            disabled={busy}
            className={cn(
              'flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors',
              'border border-purple-500/30 text-purple-400 hover:bg-purple-500/10 hover:border-purple-500/50',
              'disabled:opacity-40 disabled:cursor-not-allowed',
            )}
          >
            {isReanalyzing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
            {isReanalyzing ? 'Analyzing...' : 'Run Analysis Again'}
          </button>

          <button
            onClick={onApplyAiPatchRetry}
            disabled={busy || !canRetry || executionFailed || !onApplyAiPatchRetry}
            className={cn(
              'flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold transition-colors',
              canRetry && !executionFailed && !busy && onApplyAiPatchRetry
                ? 'border border-blue-400/40 text-blue-300 hover:bg-blue-500/10'
                : 'border border-slate-700 text-slate-600 cursor-not-allowed',
            )}
          >
            <Wand2 className="w-4 h-4" />
            Apply AI Patch & Retry
          </button>

          <button
            onClick={onApproveRetry}
            disabled={busy || !canRetry || executionFailed}
            className={cn(
              'flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition-colors',
              canRetry && !executionFailed && !busy
                ? 'bg-amber-500 hover:bg-amber-400 text-slate-900 shadow-lg shadow-amber-500/20'
                : 'bg-slate-700 text-slate-500 cursor-not-allowed',
            )}
          >
            {isRetrying ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            {isRetrying ? 'Starting build...' : 'Retry Build With Current Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}
