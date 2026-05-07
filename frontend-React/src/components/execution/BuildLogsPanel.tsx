import { useEffect, useRef, useState } from 'react'
import { Terminal, ArrowDownToLine } from 'lucide-react'
import { cn } from '@/lib/utils'
import { LogLine, type LogEntry } from './LogLine'
import { ExecutionStatusBadge, type ExecutionStatus } from './ExecutionStatusBadge'

interface Props {
  logs: LogEntry[]
  status: ExecutionStatus
  imageTag?: string
  /** When true, the panel anchors scroll to the latest line automatically */
  autoScroll?: boolean
  className?: string
}

export function BuildLogsPanel({
  logs,
  status,
  imageTag,
  autoScroll = true,
  className,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [userScrolled, setUserScrolled] = useState(false)

  // Auto-scroll when new logs arrive (unless user scrolled up)
  useEffect(() => {
    if (!autoScroll || userScrolled) return
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs.length, autoScroll, userScrolled])

  function handleScroll() {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setUserScrolled(!atBottom)
  }

  function scrollToBottom() {
    setUserScrolled(false)
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <div className={cn('flex flex-col rounded-xl overflow-hidden border border-slate-200 dark:border-white/[0.06]', className)}>
      {/* Header bar */}
      <div className={cn(
        'flex items-center justify-between px-4 py-2.5',
        'bg-slate-900 dark:bg-surface-950 border-b border-slate-700 dark:border-white/[0.06]',
      )}>
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-slate-400" />
          <span className="text-xs font-semibold text-slate-300 font-mono">Docker Build Output</span>
        </div>
        <div className="flex items-center gap-3">
          {imageTag && (
            <span className="text-[10px] font-mono text-slate-500 truncate max-w-[200px]" title={imageTag}>
              {imageTag}
            </span>
          )}
          <ExecutionStatusBadge status={status} />
        </div>
      </div>

      {/* Log body */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className={cn(
          'flex-1 overflow-y-auto bg-slate-950 px-4 py-3 space-y-0.5',
          'min-h-[320px] max-h-[520px]',
          'scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent',
        )}
      >
        {logs.length === 0 && status === 'running' && (
          <div className="flex items-center gap-2 text-slate-500 text-xs font-mono py-2">
            <span className="animate-pulse">▋</span>
            <span>Waiting for build output…</span>
          </div>
        )}
        {logs.length === 0 && status !== 'running' && (
          <p className="text-slate-500 text-xs font-mono py-2">No logs available.</p>
        )}
        {logs.map((entry, i) => (
          <LogLine key={i} entry={entry} showTimestamp={false} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Scroll-to-bottom button */}
      {userScrolled && (
        <button
          onClick={scrollToBottom}
          className={cn(
            'absolute bottom-16 right-6 z-10',
            'flex items-center gap-1.5 px-3 py-1.5 rounded-full',
            'bg-slate-800 text-slate-300 text-xs font-medium',
            'border border-slate-700 shadow-lg',
            'hover:bg-slate-700 transition-colors',
          )}
        >
          <ArrowDownToLine className="w-3 h-3" />
          Jump to bottom
        </button>
      )}

      {/* Footer: line count */}
      <div className={cn(
        'flex items-center justify-between px-4 py-1.5',
        'bg-slate-900 dark:bg-surface-950 border-t border-slate-700 dark:border-white/[0.06]',
      )}>
        <span className="text-[10px] text-slate-600 font-mono">{logs.length} lines</span>
        {status === 'running' && (
          <span className="text-[10px] text-blue-400 font-mono animate-pulse">● live</span>
        )}
        {status === 'success' && (
          <span className="text-[10px] text-emerald-400 font-mono">● build complete</span>
        )}
        {status === 'failed' && (
          <span className="text-[10px] text-red-400 font-mono">● build failed</span>
        )}
      </div>
    </div>
  )
}
