import { useState } from 'react'
import { CheckCircle2, XCircle, PlayCircle, ChevronDown, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import type { TerraformValidationResult, TerraformValidationLog } from '@/api/terraform'

interface Props {
  result: TerraformValidationResult | null
  isValidating: boolean
  onValidate: () => void
  className?: string
}

function StatusHeader({ valid, durationMs }: { valid: boolean; durationMs: number }) {
  const Icon = valid ? CheckCircle2 : XCircle
  return (
    <div className={cn(
      'flex items-center gap-3 px-4 py-3 rounded-lg',
      valid
        ? 'bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20'
        : 'bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20',
    )}>
      <Icon className={cn(
        'w-5 h-5 shrink-0',
        valid ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400',
      )} />
      <div className="flex-1 min-w-0">
        <p className={cn(
          'text-sm font-semibold',
          valid ? 'text-emerald-700 dark:text-emerald-300' : 'text-red-700 dark:text-red-300',
        )}>
          {valid ? 'Validation passed' : 'Validation failed'}
        </p>
        <p className={cn(
          'text-xs mt-0.5',
          valid ? 'text-emerald-600/70 dark:text-emerald-400/70' : 'text-red-600/70 dark:text-red-400/70',
        )}>
          terraform init + validate · {durationMs} ms
        </p>
      </div>
    </div>
  )
}

function LogSection({
  label,
  log,
  defaultOpen,
}: {
  label: string
  log: TerraformValidationLog
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(!!defaultOpen)
  const hasOutput = log.stdout.trim().length > 0 || log.stderr.trim().length > 0

  return (
    <div className={cn(
      'rounded-lg border overflow-hidden',
      'bg-white dark:bg-surface-900',
      'border-slate-200 dark:border-white/[0.06]',
    )}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'w-full flex items-center gap-2 px-4 py-2.5 text-left transition-colors',
          'hover:bg-slate-50 dark:hover:bg-white/[0.03]',
        )}
      >
        {open
          ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
          : <ChevronRight className="w-3.5 h-3.5 text-slate-400" />}
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{label}</span>
        <span className={cn(
          'ml-auto text-xs font-medium px-2 py-0.5 rounded',
          log.ok
            ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
            : 'bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400',
        )}>
          {log.ok ? 'ok' : 'failed'}
        </span>
      </button>

      {open && (
        <div className="border-t border-slate-200 dark:border-white/[0.06]">
          {!hasOutput && (
            <p className="px-4 py-3 text-xs text-slate-400 dark:text-slate-500 italic">
              No output.
            </p>
          )}
          {log.stdout.trim() && (
            <div>
              <p className="px-4 pt-3 text-[10px] uppercase tracking-wider font-medium text-slate-400 dark:text-slate-500">
                stdout
              </p>
              <pre className="px-4 pb-3 pt-1 text-xs font-mono leading-relaxed text-slate-700 dark:text-slate-300 overflow-auto max-h-64 whitespace-pre-wrap break-words">
                {log.stdout}
              </pre>
            </div>
          )}
          {log.stderr.trim() && (
            <div className={cn(log.stdout.trim() && 'border-t border-slate-200 dark:border-white/[0.06]')}>
              <p className="px-4 pt-3 text-[10px] uppercase tracking-wider font-medium text-red-500 dark:text-red-400/80">
                stderr
              </p>
              <pre className="px-4 pb-3 pt-1 text-xs font-mono leading-relaxed text-red-600 dark:text-red-400/90 overflow-auto max-h-64 whitespace-pre-wrap break-words">
                {log.stderr}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ValidationPanel({ result, isValidating, onValidate, className }: Props) {
  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
            Terraform validation
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Runs <span className="font-mono">terraform init</span> + <span className="font-mono">terraform validate</span> locally.
          </p>
        </div>
        <button
          onClick={onValidate}
          disabled={isValidating}
          className={cn(
            'flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-colors',
            'bg-brand-600 hover:bg-brand-500 text-white',
            'disabled:opacity-40 disabled:cursor-not-allowed',
          )}
        >
          {isValidating
            ? <LoadingSpinner className="w-4 h-4" />
            : <PlayCircle className="w-4 h-4" />}
          {isValidating ? 'Validating…' : 'Validate Terraform'}
        </button>
      </div>

      {result && (
        <>
          <StatusHeader valid={result.valid} durationMs={result.duration_ms} />
          <LogSection label="terraform init"     log={result.init}     defaultOpen={!result.init.ok} />
          <LogSection label="terraform validate" log={result.validate} defaultOpen={!result.validate.ok} />
        </>
      )}
    </div>
  )
}
