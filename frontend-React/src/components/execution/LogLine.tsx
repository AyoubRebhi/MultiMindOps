import { cn } from '@/lib/utils'

export type LogLevel = 'INFO' | 'WARNING' | 'ERROR' | 'SUCCESS' | 'DEFAULT'

export interface LogEntry {
  timestamp: string
  level: LogLevel
  message: string
}

const LEVEL_STYLES: Record<LogLevel, { text: string; badge: string; prefix: string }> = {
  SUCCESS: { text: 'text-emerald-400',  badge: 'text-emerald-500/80', prefix: '✓' },
  WARNING: { text: 'text-yellow-300',   badge: 'text-yellow-500/80',  prefix: '⚠' },
  ERROR:   { text: 'text-red-400',      badge: 'text-red-500/80',     prefix: '✗' },
  INFO:    { text: 'text-sky-300',      badge: 'text-sky-600/60',     prefix: ' ' },
  DEFAULT: { text: 'text-slate-300',    badge: 'text-slate-600/60',   prefix: ' ' },
}

interface Props {
  entry: LogEntry
  showTimestamp?: boolean
}

export function LogLine({ entry, showTimestamp = true }: Props) {
  const level = entry.level ?? 'DEFAULT'
  const styles = LEVEL_STYLES[level] ?? LEVEL_STYLES.DEFAULT

  const timeStr = showTimestamp
    ? new Date(entry.timestamp).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      })
    : null

  return (
    <div className={cn('flex gap-2 font-mono text-xs leading-5', styles.text)}>
      {timeStr && (
        <span className="shrink-0 text-slate-600 select-none w-[60px]">{timeStr}</span>
      )}
      <span className={cn('select-none shrink-0 w-3 text-center', styles.badge)}>
        {styles.prefix}
      </span>
      <span className="break-all whitespace-pre-wrap min-w-0">{entry.message}</span>
    </div>
  )
}
