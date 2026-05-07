import { cn } from '@/lib/utils'

export type LogLevel = 'INFO' | 'ERROR' | 'SUCCESS' | 'DEFAULT'

export interface LogEntry {
  timestamp: string
  level: LogLevel
  message: string
}

const LEVEL_CLASSES: Record<LogLevel, string> = {
  SUCCESS: 'text-emerald-400',
  ERROR:   'text-red-400',
  INFO:    'text-blue-300',
  DEFAULT: 'text-slate-300',
}

const LEVEL_PREFIX: Record<LogLevel, string> = {
  SUCCESS: '✓ ',
  ERROR:   '✗ ',
  INFO:    '  ',
  DEFAULT: '  ',
}

interface Props {
  entry: LogEntry
  showTimestamp?: boolean
}

export function LogLine({ entry, showTimestamp = false }: Props) {
  const timeStr = showTimestamp
    ? new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : null

  return (
    <div className={cn('flex gap-2 font-mono text-xs leading-5', LEVEL_CLASSES[entry.level ?? 'DEFAULT'])}>
      {timeStr && (
        <span className="shrink-0 text-slate-600 select-none">{timeStr}</span>
      )}
      <span className="select-none shrink-0">{LEVEL_PREFIX[entry.level ?? 'DEFAULT']}</span>
      <span className="break-all whitespace-pre-wrap">{entry.message}</span>
    </div>
  )
}
