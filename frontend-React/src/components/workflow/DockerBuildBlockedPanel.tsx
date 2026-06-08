import { ShieldAlert, RefreshCcw, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DockerBuildBlocked } from '@/services/workflowApi'

/** Reason code → human-readable headline. Falls back to the raw code so an
 *  unknown future reason still renders something meaningful. */
const REASON_LABELS: Record<string, string> = {
  UNRESOLVED_TEMPLATE_TOKEN: 'Unresolved template token(s) in generated artifacts',
  RUNTIME_VALIDATION_FAILED: 'Dockerfile failed runtime validation',
  UNRESOLVED_BUILD_CONTEXT: 'COPY / build-context paths could not be resolved',
}

function readableReason(reason: string): string {
  return REASON_LABELS[reason] ?? reason.replace(/_/g, ' ').toLowerCase()
}

interface Props {
  blocked: DockerBuildBlocked
  /** "Fix & Retry Build" CTA — re-generates the Docker artifacts (the fix) so
   *  the user can build again on clean, fully-rendered artifacts. */
  onRetry: () => void
  retrying?: boolean
  canRun?: boolean
}

/**
 * Red, explicit panel shown when the backend PrebuildGate blocks a Docker build
 * (HTTP 422). Surfaces the structured reason + details so the user understands
 * exactly why no build started — replacing the previous silent "200 OK but
 * nothing happens" dead state.
 */
export function DockerBuildBlockedPanel({ blocked, onRetry, retrying = false, canRun = true }: Props) {
  const details = blocked.details ?? []
  return (
    <div
      role="alert"
      className="rounded-lg border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10 overflow-hidden"
    >
      <div className="flex items-center gap-2 px-3 py-2 border-b border-red-200/70 dark:border-red-500/20">
        <ShieldAlert className="w-4 h-4 text-red-600 dark:text-red-400 shrink-0" />
        <span className="text-sm font-semibold text-red-700 dark:text-red-300">Build Blocked</span>
      </div>

      <div className="p-3 space-y-2.5">
        <p className="text-xs text-red-700 dark:text-red-300">
          {blocked.message || readableReason(blocked.reason)}
        </p>

        <div className="text-[11px] font-mono text-red-600/80 dark:text-red-400/80">
          reason: {blocked.reason}
        </div>

        {details.length > 0 && (
          <ul className="space-y-1 text-[11px] text-red-700 dark:text-red-300">
            {details.map((d, i) => (
              <li key={i} className="flex gap-1.5">
                <span className="text-red-400 select-none">•</span>
                <span className="break-all">{d}</span>
              </li>
            ))}
          </ul>
        )}

        <button
          onClick={onRetry}
          disabled={!canRun || retrying}
          title={!canRun ? 'Read-only role' : undefined}
          className={cn(
            'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium',
            'border border-red-300 dark:border-red-500/40 bg-white dark:bg-surface-900/40',
            'text-red-700 dark:text-red-300 hover:bg-red-100/60 dark:hover:bg-red-500/15',
            'disabled:opacity-50 disabled:cursor-not-allowed transition-colors',
          )}
        >
          {retrying ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <RefreshCcw className="w-3.5 h-3.5" />
          )}
          Fix &amp; Retry Build
        </button>
      </div>
    </div>
  )
}
