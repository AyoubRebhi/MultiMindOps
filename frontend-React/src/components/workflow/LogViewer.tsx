import { useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'
import type { LogEntry } from '@/types'

interface Props {
  logs: LogEntry[]
  className?: string
  autoScroll?: boolean
}

function levelStyle(level?: string) {
  switch (level) {
    case 'error':   return 'text-red-400'
    case 'warning': return 'text-amber-400'
    case 'success': return 'text-emerald-400'
    case 'debug':   return 'text-slate-500'
    default:        return 'text-slate-300'
  }
}

function levelPrefix(level?: string) {
  switch (level) {
    case 'error':   return '✗'
    case 'warning': return '⚠'
    case 'success': return '✓'
    default:        return '›'
  }
}

export function LogViewer({ logs, className, autoScroll = true }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, autoScroll])

  if (!logs.length) {
    return (
      <div className={cn('flex items-center justify-center h-32 text-sm text-slate-600', className)}>
        No logs yet…
      </div>
    )
  }

  return (
    <div
      className={cn(
        'font-mono text-xs bg-surface-950 rounded-lg border border-white/[0.06] overflow-y-auto p-4 space-y-0.5',
        className ?? 'h-64'
      )}
    >
      {logs.map((log, i) => {
        const msg =
          typeof log === 'string'
            ? log
            : log.message ?? log.step ?? JSON.stringify(log)
        const level = typeof log === 'object' ? log.level : undefined
        const agent = typeof log === 'object' ? log.agent ?? log.step : undefined
        const ts    = typeof log === 'object' ? log.timestamp : undefined

        return (
          <div key={i} className={cn('flex gap-2', levelStyle(level))}>
            <span className="text-slate-600 shrink-0">{levelPrefix(level)}</span>
            {ts && (
              <span className="text-slate-600 shrink-0">
                {new Date(ts).toLocaleTimeString()}
              </span>
            )}
            {agent && (
              <span className="text-brand-500 shrink-0">[{String(agent)}]</span>
            )}
            <span className="break-all">{String(msg)}</span>
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}
