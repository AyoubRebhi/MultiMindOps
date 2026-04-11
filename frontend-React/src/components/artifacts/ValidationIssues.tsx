import { AlertTriangle, XCircle, Info, CheckCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ValidationResult } from '@/types'

interface Props {
  validation: ValidationResult
  className?: string
}

export function ValidationIssues({ validation, className }: Props) {
  const missing  = validation.missing_artifacts  ?? []
  const quality  = validation.quality_issues      ?? []
  const warnings = validation.warnings            ?? []

  if (!missing.length && !quality.length && !warnings.length) {
    return (
      <div className={cn(
        'flex items-center gap-2 p-3 rounded-lg',
        'bg-emerald-50 dark:bg-emerald-500/10',
        'border border-emerald-200 dark:border-emerald-500/20',
        className,
      )}>
        <CheckCircle className="w-4 h-4 text-emerald-500 shrink-0" />
        <p className="text-sm text-emerald-700 dark:text-emerald-300">
          All required artifacts generated successfully.
        </p>
      </div>
    )
  }

  return (
    <div className={cn('space-y-3', className)}>
      {/* Missing artifacts */}
      {missing.length > 0 && (
        <div className={cn(
          'rounded-lg overflow-hidden',
          'border border-red-200 dark:border-red-500/20',
        )}>
          <div className={cn(
            'flex items-center gap-2 px-3 py-2',
            'bg-red-50 dark:bg-red-500/10',
            'border-b border-red-100 dark:border-red-500/15',
          )}>
            <XCircle className="w-4 h-4 text-red-500 shrink-0" />
            <span className="text-xs font-medium text-red-700 dark:text-red-300">
              Missing artifacts ({missing.length})
            </span>
          </div>
          <ul className="divide-y divide-red-100 dark:divide-red-500/10">
            {missing.map((name) => (
              <li
                key={name}
                className="flex items-center gap-2 px-3 py-2 bg-white dark:bg-surface-800/40"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0" />
                <span className="text-xs font-mono text-red-600 dark:text-red-400">{name}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Quality issues */}
      {quality.length > 0 && (
        <div className={cn(
          'rounded-lg overflow-hidden',
          'border border-amber-200 dark:border-amber-500/20',
        )}>
          <div className={cn(
            'flex items-center gap-2 px-3 py-2',
            'bg-amber-50 dark:bg-amber-500/10',
            'border-b border-amber-100 dark:border-amber-500/15',
          )}>
            <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0" />
            <span className="text-xs font-medium text-amber-700 dark:text-amber-300">
              Quality issues ({quality.length})
            </span>
          </div>
          <ul className="divide-y divide-amber-100 dark:divide-amber-500/10">
            {quality.map((issue, i) => (
              <li
                key={i}
                className="flex items-start gap-2 px-3 py-2 bg-white dark:bg-surface-800/40"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0 mt-1.5" />
                <span className="text-xs text-amber-700 dark:text-amber-300">{issue}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className={cn(
          'rounded-lg overflow-hidden',
          'border border-blue-200 dark:border-blue-500/20',
        )}>
          <div className={cn(
            'flex items-center gap-2 px-3 py-2',
            'bg-blue-50 dark:bg-blue-500/10',
            'border-b border-blue-100 dark:border-blue-500/15',
          )}>
            <Info className="w-4 h-4 text-blue-500 shrink-0" />
            <span className="text-xs font-medium text-blue-700 dark:text-blue-300">
              Warnings ({warnings.length})
            </span>
          </div>
          <ul className="divide-y divide-blue-100 dark:divide-blue-500/10">
            {warnings.map((w, i) => (
              <li
                key={i}
                className="flex items-start gap-2 px-3 py-2 bg-white dark:bg-surface-800/40"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0 mt-1.5" />
                <span className="text-xs text-blue-700 dark:text-blue-300">{w}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
