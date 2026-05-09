import { AlertTriangle, XCircle, RefreshCw, CheckCircle2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  retryCount: number
  maxRetries: number
  executionFailed?: boolean
  className?: string
}

export function RetryLifecycleBadge({
  retryCount,
  maxRetries,
  executionFailed = false,
  className,
}: Props) {
  const remaining = maxRetries - retryCount
  const isFinal   = retryCount === maxRetries - 1 && !executionFailed
  const isExhausted = executionFailed || retryCount >= maxRetries

  if (isExhausted) {
    return (
      <div className={cn(
        'inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-semibold',
        'bg-red-500/10 border border-red-500/30 text-red-400',
        className,
      )}>
        <XCircle className="w-4 h-4 shrink-0" />
        <span>Remediation Failed</span>
        <span className="text-xs font-mono opacity-70">({retryCount}/{maxRetries} attempts)</span>
      </div>
    )
  }

  if (isFinal) {
    return (
      <div className={cn(
        'inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-semibold',
        'bg-orange-500/10 border border-orange-500/30 text-orange-400',
        className,
      )}>
        <AlertTriangle className="w-4 h-4 shrink-0 animate-pulse" />
        <span>Final Attempt</span>
        <span className="text-xs font-mono opacity-70">({retryCount + 1}/{maxRetries})</span>
      </div>
    )
  }

  if (retryCount === 0) {
    return (
      <div className={cn(
        'inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-semibold',
        'bg-amber-500/10 border border-amber-500/30 text-amber-400',
        className,
      )}>
        <RefreshCw className="w-4 h-4 shrink-0" />
        <span>First Retry Available</span>
        <span className="text-xs font-mono opacity-70">({remaining} left)</span>
      </div>
    )
  }

  return (
    <div className={cn(
      'inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-semibold',
      'bg-amber-500/10 border border-amber-500/30 text-amber-400',
      className,
    )}>
      <RefreshCw className="w-4 h-4 shrink-0" />
      <span>Retry {retryCount + 1}/{maxRetries}</span>
      <span className="text-xs font-mono opacity-70">({remaining} remaining)</span>
    </div>
  )
}

// ── Compact retry history dots ─────────────────────────────────────────────────

interface HistoryDotsProps {
  retryCount: number
  maxRetries: number
  executionFailed?: boolean
}

export function RetryHistoryDots({ retryCount, maxRetries, executionFailed }: HistoryDotsProps) {
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: maxRetries }).map((_, i) => {
        const done    = i < retryCount
        const current = i === retryCount && !executionFailed
        const failed  = executionFailed && i === retryCount - 1
        return (
          <div
            key={i}
            title={done ? `Attempt ${i + 1}: failed` : current ? 'Current attempt' : `Attempt ${i + 1}: pending`}
            className={cn(
              'w-2.5 h-2.5 rounded-full transition-all',
              done || failed   ? 'bg-red-500'           : '',
              current          ? 'bg-amber-400 animate-pulse scale-125' : '',
              !done && !current && !failed ? 'bg-slate-600' : '',
            )}
          />
        )
      })}
    </div>
  )
}

// ── Confidence ring ────────────────────────────────────────────────────────────

interface ConfidenceProps {
  confidence: number
}

export function ConfidenceBadge({ confidence }: ConfidenceProps) {
  const pct = Math.round(confidence * 100)
  const color =
    pct >= 85 ? 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10'
    : pct >= 65 ? 'text-amber-400 border-amber-500/40 bg-amber-500/10'
    : 'text-red-400 border-red-500/40 bg-red-500/10'

  return (
    <div className={cn(
      'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold border',
      color,
    )}>
      <CheckCircle2 className="w-3.5 h-3.5" />
      <span>{pct}% confidence</span>
    </div>
  )
}
