import { AlertTriangle, Terminal, Tag, RefreshCw, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { CorrectorAnalysis } from '@/services/correctorApi'
import { RetryLifecycleBadge, RetryHistoryDots, ConfidenceBadge } from './RetryLifecycleBadge'

interface Props {
  analysis: CorrectorAnalysis
  retryCount: number
  maxRetries: number
  executionFailed: boolean
}

function MetaRow({
  icon: Icon,
  label,
  value,
  mono = false,
  valueClass = '',
}: {
  icon: React.ElementType
  label: string
  value?: string | null
  mono?: boolean
  valueClass?: string
}) {
  if (!value) return null
  return (
    <div className="flex items-start gap-3">
      <div className="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center bg-slate-800 border border-slate-700">
        <Icon className="w-3.5 h-3.5 text-slate-400" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] uppercase tracking-widest text-slate-500 font-medium mb-0.5">{label}</p>
        <p className={cn(
          'text-sm text-slate-200 leading-tight break-words',
          mono && 'font-mono text-red-300',
          valueClass,
        )}>
          {value}
        </p>
      </div>
    </div>
  )
}

const ERROR_TYPE_LABELS: Record<string, string> = {
  permission_failure:    'Permission / chmod error',
  network_failure:       'Network / connectivity error',
  dependency_failure:    'Package / dependency not found',
  syntax_error:          'Dockerfile syntax error',
  resource_failure:      'Out of memory / disk space',
  build_tool_failure:    'Build tool failure (Maven, npm, etc.)',
  authentication_error:  'Registry authentication failed',
  unknown:               'Unknown error',
}

export function FailureSummaryCard({ analysis, retryCount, maxRetries, executionFailed }: Props) {
  const errorTypeLabel =
    analysis.error_type
      ? (ERROR_TYPE_LABELS[analysis.error_type] ?? analysis.error_type.replace(/_/g, ' '))
      : null

  return (
    <div className={cn(
      'rounded-xl overflow-hidden border',
      executionFailed
        ? 'border-red-500/40 bg-[#130808]'
        : 'border-amber-500/25 bg-[#0d1117]',
    )}>
      {/* Header */}
      <div className={cn(
        'flex items-center justify-between px-5 py-3.5 border-b',
        executionFailed
          ? 'bg-red-500/10 border-red-500/30'
          : 'bg-amber-500/5 border-amber-500/20',
      )}>
        <div className="flex items-center gap-2.5">
          {executionFailed
            ? <XCircle className="w-5 h-5 text-red-400 shrink-0" />
            : <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0" />}
          <div>
            <p className={cn(
              'text-sm font-bold',
              executionFailed ? 'text-red-300' : 'text-amber-200',
            )}>
              {executionFailed ? 'Automatic Remediation Limit Reached' : 'Docker Build Failed'}
            </p>
            <p className="text-xs text-slate-500 mt-0.5">
              {executionFailed
                ? 'Manual inspection required — all retry attempts exhausted'
                : 'AI corrector has analyzed the failure and suggests fixes below'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {analysis.confidence != null && (
            <ConfidenceBadge confidence={analysis.confidence} />
          )}
          <RetryLifecycleBadge
            retryCount={retryCount}
            maxRetries={maxRetries}
            executionFailed={executionFailed}
          />
        </div>
      </div>

      {/* Body */}
      <div className="px-5 py-4 space-y-4">
        {/* Retry history dots */}
        {maxRetries > 1 && (
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-500 font-medium w-24 shrink-0">Build history</span>
            <RetryHistoryDots
              retryCount={retryCount}
              maxRetries={maxRetries}
              executionFailed={executionFailed}
            />
            <span className="text-xs text-slate-600 font-mono ml-1">
              {retryCount} / {maxRetries} attempts
            </span>
          </div>
        )}

        {/* Meta grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
          <MetaRow
            icon={Tag}
            label="Error Type"
            value={errorTypeLabel}
            valueClass="capitalize"
          />
          <MetaRow
            icon={Terminal}
            label="Failed Step"
            value={analysis.failed_step}
            mono
          />
          <MetaRow
            icon={RefreshCw}
            label="Retry Recommended"
            value={analysis.retry_recommended != null
              ? (analysis.retry_recommended ? 'Yes — AI fix available' : 'No — manual review needed')
              : null}
          />
        </div>

        {/* Root cause */}
        {analysis.root_cause && (
          <div className="pt-1 border-t border-slate-800">
            <p className="text-[10px] uppercase tracking-widest text-slate-500 font-medium mb-2">Root Cause</p>
            <p className="text-sm text-slate-300 leading-relaxed">{analysis.root_cause}</p>
          </div>
        )}
      </div>
    </div>
  )
}
