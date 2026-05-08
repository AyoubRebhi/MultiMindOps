import { useEffect, useRef, useState } from 'react'
import { Terminal, ArrowDownToLine, Hash } from 'lucide-react'
import { cn } from '@/lib/utils'
import { LogLine, type LogEntry } from './LogLine'
import { ExecutionStatusBadge, type ExecutionStatus } from './ExecutionStatusBadge'

interface Props {
  logs: LogEntry[]
  status: ExecutionStatus
  imageTag?: string
  retries?: number
  buildNumber?: number
  durationSeconds?: number | null
  autoScroll?: boolean
  className?: string
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

export function BuildLogsPanel({
  logs,
  status,
  imageTag,
  retries = 0,
  buildNumber,
  durationSeconds,
  autoScroll = true,
  className,
}: Props) {
  const bottomRef    = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [userScrolled, setUserScrolled] = useState(false)
  const [liveDuration, setLiveDuration] = useState<number | null>(null)
  const startTimeRef = useRef<number | null>(null)
  const timerRef     = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── Live duration counter ─────────────────────────────────────────────────
  useEffect(() => {
    if (status === 'running' || status === 'retrying') {
      if (!startTimeRef.current) startTimeRef.current = Date.now()
      timerRef.current = setInterval(() => {
        const elapsed = Math.floor((Date.now() - startTimeRef.current!) / 1000)
        setLiveDuration(elapsed)
      }, 1_000)
    } else {
      if (timerRef.current) clearInterval(timerRef.current)
      startTimeRef.current = null
      setLiveDuration(null)
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [status])

  // ── Auto-scroll ───────────────────────────────────────────────────────────
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

  const displayDuration =
    durationSeconds !== null && durationSeconds !== undefined
      ? formatDuration(durationSeconds)
      : liveDuration !== null
      ? formatDuration(liveDuration)
      : null

  // ── Log level counters ────────────────────────────────────────────────────
  const infoCount    = logs.filter((l) => l.level === 'INFO').length
  const successCount = logs.filter((l) => l.level === 'SUCCESS').length
  const warnCount    = logs.filter((l) => l.level === 'WARNING').length
  const errorCount   = logs.filter((l) => l.level === 'ERROR').length

  return (
    <div className={cn('flex flex-col rounded-xl overflow-hidden border border-slate-700', className)}>

      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-[#0d1117] border-b border-slate-700/80">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full bg-red-500/80" />
            <span className="w-3 h-3 rounded-full bg-yellow-500/80" />
            <span className="w-3 h-3 rounded-full bg-green-500/80" />
          </div>
          <Terminal className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-xs font-semibold text-slate-200 font-mono tracking-wide">
            Docker Build Output
          </span>
          {buildNumber !== undefined && buildNumber > 0 && (
            <span className="flex items-center gap-0.5 text-[10px] font-mono text-slate-500">
              <Hash className="w-2.5 h-2.5" />{buildNumber}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {imageTag && (
            <span className="text-[10px] font-mono text-slate-500 truncate max-w-[180px]" title={imageTag}>
              {imageTag}
            </span>
          )}
          {retries > 0 && (
            <span className="text-[10px] font-mono text-amber-400" title={`${retries} retry attempt${retries !== 1 ? 's' : ''}`}>
              ↻ {retries}
            </span>
          )}
          <ExecutionStatusBadge status={status} />
        </div>
      </div>

      {/* ── Live level counters bar ───────────────────────────────────────── */}
      {logs.length > 0 && (
        <div className="flex items-center gap-3 px-4 py-1.5 bg-[#0d1117] border-b border-slate-800">
          {infoCount > 0 && (
            <span className="flex items-center gap-1 text-[10px] font-mono text-sky-400 bg-sky-900/25 px-1.5 py-0.5 rounded">
              <span className="select-none">ℹ</span> {infoCount} INFO
            </span>
          )}
          {successCount > 0 && (
            <span className="flex items-center gap-1 text-[10px] font-mono text-emerald-400 bg-emerald-900/25 px-1.5 py-0.5 rounded">
              <span className="select-none">✓</span> {successCount} OK
            </span>
          )}
          {warnCount > 0 && (
            <span className="flex items-center gap-1 text-[10px] font-mono text-yellow-400 bg-yellow-900/25 px-1.5 py-0.5 rounded">
              <span className="select-none">⚠</span> {warnCount} WARN
            </span>
          )}
          {errorCount > 0 && (
            <span className="flex items-center gap-1 text-[10px] font-mono text-red-400 bg-red-900/25 px-1.5 py-0.5 rounded">
              <span className="select-none">✗</span> {errorCount} ERR
            </span>
          )}
          <span className="ml-auto text-[10px] font-mono text-slate-600">
            {logs.length} lines total
          </span>
        </div>
      )}

      {/* ── Log body ─────────────────────────────────────────────────────── */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className={cn(
          'flex-1 overflow-y-auto bg-[#0d1117] px-4 py-3 space-y-0.5',
          'min-h-[340px] max-h-[540px]',
          'scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent',
        )}
      >
        {logs.length === 0 && (status === 'running' || status === 'retrying') && (
          <div className="flex items-center gap-2 text-slate-500 text-xs font-mono py-2">
            <span className="animate-pulse text-green-400">▋</span>
            <span>Waiting for build output…</span>
          </div>
        )}
        {logs.length === 0 && status === 'pending' && (
          <div className="flex items-center gap-2 text-slate-600 text-xs font-mono py-2">
            <span>Initializing Docker build…</span>
          </div>
        )}
        {logs.length === 0 && status !== 'running' && status !== 'retrying' && status !== 'pending' && (
          <p className="text-slate-600 text-xs font-mono py-2">No logs available.</p>
        )}
        {logs.map((entry, i) => (
          <LogLine key={`${entry.timestamp}-${i}`} entry={entry} showTimestamp />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* ── Jump-to-bottom ────────────────────────────────────────────────── */}
      {userScrolled && (
        <button
          onClick={scrollToBottom}
          className={cn(
            'absolute bottom-16 right-6 z-10',
            'flex items-center gap-1.5 px-3 py-1.5 rounded-full',
            'bg-slate-800 text-slate-300 text-xs font-medium',
            'border border-slate-600 shadow-lg',
            'hover:bg-slate-700 transition-colors',
          )}
        >
          <ArrowDownToLine className="w-3 h-3" />
          Jump to bottom
        </button>
      )}

      {/* ── Footer ───────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-1.5 bg-[#0d1117] border-t border-slate-700/80">
        <span className="text-[10px] text-slate-600 font-mono">{logs.length} lines</span>
        <div className="flex items-center gap-3">
          {displayDuration && (
            <span className="text-[10px] text-slate-500 font-mono">⏱ {displayDuration}</span>
          )}
          {(status === 'running' || status === 'retrying') && (
            <span className="text-[10px] text-blue-400 font-mono animate-pulse">● live</span>
          )}
          {status === 'success' && (
            <span className="text-[10px] text-emerald-400 font-mono">✓ build complete</span>
          )}
          {status === 'failed' && (
            <span className="text-[10px] text-red-400 font-mono">✗ build failed</span>
          )}
        </div>
      </div>
    </div>
  )
}
