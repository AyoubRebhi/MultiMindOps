import { useCallback, useEffect, useRef, useState } from 'react'
import { Container, RefreshCw, ChevronRight, AlertTriangle, Terminal, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { BuildLogsPanel } from '@/components/execution/BuildLogsPanel'
import type { ExecutionStatus } from '@/components/execution/ExecutionStatusBadge'
import type { LogEntry } from '@/components/execution/LogLine'
import { useWorkflowStore } from '@/store/workflowStore'
import { getWsExecutionUrl, startDockerBuild, getDockerBuildStatus } from '@/services/workflowApi'

// ── Types ──────────────────────────────────────────────────────────────────────

interface WsMessage {
  timestamp?: string
  level?: string
  message?: string
  type?: 'log' | 'complete' | 'done' | 'error' | 'pong' | 'info'
  status?: string
  exit_code?: number | null
  is_replay?: boolean
  retry_iteration?: number
  execution_session_id?: string
  metadata?: { retry_iteration?: number; execution_session_id?: string }
}

export interface RetryTimelineEntry {
  retry_iteration: number
  execution_session_id?: string
  state: 'building' | 'success' | 'failed' | 'analyzing' | 'patch_generated'
  started_at: string
  finished_at?: string
  message?: string
}

interface FailureDiagnostics {
  failure_reason: string | null
  docker_command: string | null
  last_error_line: string | null
  failed_step: string | null
}

interface Props {
  onContinue: () => void
  onBack: () => void
  isPhaseLoading?: boolean
}

// ── Component ──────────────────────────────────────────────────────────────────

export function DockerBuildStep({ onContinue, onBack, isPhaseLoading }: Props) {
  const { taskId, currentPhase, mergePhaseResponse } = useWorkflowStore()

  const [logs, setLogs] = useState<LogEntry[]>([])           // live logs for current retry only
  const [replayLogs, setReplayLogs] = useState<LogEntry[]>([]) // logs from previous segments
  const [status, setStatus] = useState<ExecutionStatus>('pending')
  const [imageTag, setImageTag] = useState<string>()
  const [error, setError] = useState<string>()
  const [wsParseError, setWsParseError] = useState<string>()
  const [retryCount, setRetryCount] = useState(0)
  const [buildNumber, setBuildNumber] = useState(1)
  const [durationSeconds, setDurationSeconds] = useState<number | null>(null)
  const [failureDiagnostics, setFailureDiagnostics] = useState<FailureDiagnostics | null>(null)
  const [activeSessionId, setActiveSessionId] = useState<string | undefined>(undefined)
  const [retryTimeline, setRetryTimeline] = useState<RetryTimelineEntry[]>([])
  const [isLive, setIsLive] = useState(false)

  // ── Refs ──────────────────────────────────────────────────────────────────
  const buildStartedRef    = useRef(false)
  const buildInProgressRef = useRef(false)
  const wsRef              = useRef<WebSocket | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const heartbeatIntervalRef = useRef<NodeJS.Timeout | null>(null)
  // isMountedRef starts true. The cleanup effect RESETS it to true on every
  // mount/remount so React StrictMode's simulated double-mount doesn't leave it
  // permanently false (StrictMode: mount → cleanup sets false → remount, but
  // useRef does NOT reset — so we must reset it manually inside the effect body).
  const isMountedRef = useRef(true)

  // ── Debug: log whenever logs or status change ──────────────────────────────
  useEffect(() => {
    console.log('[RENDER] logs.length =', logs.length, '| status =', status)
  }, [logs, status])

  // ── Restore from DB on mount ───────────────────────────────────────────────
  useEffect(() => {
    if (!taskId) return

    getDockerBuildStatus(taskId)
      .then((data) => {
        if (!isMountedRef.current) return

        console.log('[DockerBuild] Restored state from DB:', {
          status: data.status,
          current_phase: data.current_phase,
          retries: data.retries,
          build_number: data.build_number,
          log_count: data.logs?.length ?? 0,
        })

        if (data.logs && data.logs.length > 0) {
          setLogs(data.logs as LogEntry[])
        }

        const dbStatus = data.status as ExecutionStatus
        if (dbStatus === 'success') {
          setStatus('success')
          buildStartedRef.current = true
          buildInProgressRef.current = false
        } else if (dbStatus === 'failed') {
          setStatus('failed')
          buildStartedRef.current = true
          buildInProgressRef.current = false
        } else if (dbStatus === 'running') {
          setStatus('running')
          buildStartedRef.current = true
          buildInProgressRef.current = true
        }

        setImageTag(data.image_tag ?? undefined)
        setRetryCount(data.retries ?? 0)
        setBuildNumber(data.build_number ?? 1)
        setDurationSeconds(data.duration_seconds ?? null)
        setFailureDiagnostics({
          failure_reason: data.failure_reason ?? null,
          docker_command: data.docker_command ?? null,
          last_error_line: data.last_error_line ?? null,
          failed_step: data.failed_step ?? null,
        })

        // Page-refresh recovery: reconnect only if auto-start won't handle it
        // (auto-start fires when currentPhase === 'docker_completed'; if the
        // phase is 'docker_build_running' that effect is skipped, so we connect
        // here instead). Guard with !buildInProgressRef prevents double-connect
        // when auto-start is mid-flight.
        if (
          (data.status === 'running' || data.current_phase === 'docker_build_running') &&
          !buildInProgressRef.current
        ) {
          console.log('[DockerBuild] Page-refresh recovery: connecting to live WS stream')
          connectWebSocket()
        }
      })
      .catch(() => {})
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId])

  // ── Auto-start build when phase is docker_completed ───────────────────────
  useEffect(() => {
    if (currentPhase !== 'docker_completed') return
    if (buildStartedRef.current) {
      console.log('[DockerBuild] SKIPPED DUPLICATE — buildStartedRef already true')
      return
    }
    console.log('[DockerBuild] AUTO START — phase is docker_completed')
    buildStartedRef.current = true
    startBuild()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPhase])

  // ── Cleanup on unmount — ALSO resets isMountedRef for StrictMode ──────────
  // React StrictMode: mount → cleanup runs (sets isMountedRef.current = false)
  // → remount. useRef does NOT auto-reset on remount, so we must set it to
  // true here so the guard in connectWebSocket() passes after remount.
  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      cleanupWebSocket()
    }
  }, [])

  function cleanupWebSocket() {
    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current)
      heartbeatIntervalRef.current = null
    }
    wsRef.current?.close()
    wsRef.current = null
  }

  // ── WebSocket connection ───────────────────────────────────────────────────
  const connectWebSocket = useCallback(() => {
    if (!taskId) {
      console.warn('[WS] connectWebSocket called without taskId — skipping')
      return
    }
    if (!isMountedRef.current) {
      console.warn('[WS] connectWebSocket called after unmount — skipping')
      return
    }

    cleanupWebSocket()

    const wsUrl = getWsExecutionUrl(taskId)
    console.log('[WS] Connecting to', wsUrl)
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws
    reconnectAttemptsRef.current = 0

    heartbeatIntervalRef.current = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, 30_000)

    ws.onopen = () => {
      console.log('[WS] Connected: task_id =', taskId, '| readyState =', ws.readyState)
      reconnectAttemptsRef.current = 0
    }

    ws.onmessage = (evt) => {
      // ── RAW message logging (always) ─────────────────────────────────────
      const rawData = evt.data as string
      console.log('[WS RAW]', rawData.length > 300 ? rawData.slice(0, 300) + '…' : rawData)

      // ── Parse ─────────────────────────────────────────────────────────────
      let msg: WsMessage
      try {
        msg = JSON.parse(rawData) as WsMessage
      } catch (parseErr) {
        console.error('[WS PARSE ERROR]', parseErr, '| raw payload:', rawData.slice(0, 300))
        if (isMountedRef.current) {
          setWsParseError(
            `WebSocket JSON parse failed: ${String(parseErr)} — ` +
            `raw: "${rawData.slice(0, 100)}"`
          )
        }
        return
      }
      console.log('[WS PARSED]', msg)

      // ── Build complete ────────────────────────────────────────────────────
      if (msg.type === 'complete' || msg.type === 'done') {
        const finalStatus: ExecutionStatus = msg.status === 'success' ? 'success' : 'failed'
        if (isMountedRef.current) {
          setStatus(finalStatus)
          setIsLive(false)
          if (activeSessionId) {
            setRetryTimeline((prev) =>
              prev.map((e) =>
                e.execution_session_id === activeSessionId
                  ? {
                      ...e,
                      state: finalStatus === 'success' ? 'success' : 'failed',
                      finished_at: msg.timestamp ?? new Date().toISOString(),
                    }
                  : e,
              ),
            )
          }
        }
        buildInProgressRef.current = false
        console.log('[DockerBuild] Build completed:', finalStatus, '| exit_code:', msg.exit_code)
        mergePhaseResponse({
          task_id: taskId,
          current_phase: finalStatus === 'success' ? 'docker_build_success' : 'docker_build_failed',
          status: finalStatus === 'success' ? 'in_progress' : 'failed',
          artifacts: {},
          terraform_outputs: {},
          logs: [],
          message: '',
        })
        getDockerBuildStatus(taskId)
          .then((data) => {
            if (!isMountedRef.current) return
            setFailureDiagnostics({
              failure_reason: data.failure_reason ?? null,
              docker_command: data.docker_command ?? null,
              last_error_line: data.last_error_line ?? null,
              failed_step: data.failed_step ?? null,
            })
            setDurationSeconds(data.duration_seconds ?? null)
          })
          .catch(() => {})
        if (heartbeatIntervalRef.current) {
          clearInterval(heartbeatIntervalRef.current)
          heartbeatIntervalRef.current = null
        }
        return
      }

      // ── WS-level error ────────────────────────────────────────────────────
      if (msg.type === 'error') {
        console.error('[WS] Server error event:', msg.message)
        if (isMountedRef.current) {
          setError(msg.message ?? 'WebSocket server error')
        }
        return
      }

      // ── Heartbeat / info ──────────────────────────────────────────────────
      if (msg.type === 'pong' || msg.type === 'info') {
        console.log('[WS] Non-log event:', msg.type, msg.message ?? '')
        return
      }

      // ── Retry session lifecycle events (build_started / retry_started /
      //    retry_completed / retry_failed / build_blocked_*) ────────────────
      // These arrive as type=log here because the WS emits all events
      // serialised through the log channel. We disambiguate by message text
      // and by session_id transition.
      const sessionId =
        msg.execution_session_id ??
        msg.metadata?.execution_session_id ??
        undefined
      const iteration =
        msg.retry_iteration ?? msg.metadata?.retry_iteration ?? undefined

      // Session transition → reset live buffer, move old logs to replay
      if (
        sessionId &&
        !msg.is_replay &&
        sessionId !== activeSessionId &&
        isMountedRef.current
      ) {
        console.log('[WS] New session detected:', sessionId, '(was:', activeSessionId, ')')
        setActiveSessionId(sessionId)
        setReplayLogs((prev) => [...prev, ...logs])
        setLogs([])
        setIsLive(true)
        if (iteration !== undefined) {
          setRetryTimeline((prev) => {
            // append or upsert entry
            const existing = prev.findIndex((e) => e.execution_session_id === sessionId)
            const next: RetryTimelineEntry = {
              retry_iteration: iteration,
              execution_session_id: sessionId,
              state: 'building',
              started_at: msg.timestamp ?? new Date().toISOString(),
            }
            if (existing >= 0) {
              const copy = [...prev]
              copy[existing] = { ...copy[existing], ...next }
              return copy
            }
            return [...prev, next]
          })
        }
      }

      // ── Log line ──────────────────────────────────────────────────────────
      if (msg.type === 'log' || (!msg.type && msg.message)) {
        if (!msg.message) {
          console.warn('[WS] Log-typed message has no message field — skipping')
          return
        }
        const incomingLog: LogEntry = {
          timestamp: msg.timestamp ?? new Date().toISOString(),
          level:     (msg.level ?? 'DEFAULT') as LogEntry['level'],
          message:   msg.message,
        }
        const replay = !!msg.is_replay

        const targetSetter = replay ? setReplayLogs : setLogs
        targetSetter((prev) => {
          const isDuplicate = prev.some(
            (e) => e.timestamp === incomingLog.timestamp && e.message === incomingLog.message
          )
          if (isDuplicate) return prev
          return [...prev, incomingLog]
        })
        if (!replay) setIsLive(true)
      } else {
        console.warn('[WS] Unrecognised message type:', msg.type, msg)
      }
    }

    ws.onerror = (err) => {
      console.error('[WS] onerror event:', err)
    }

    ws.onclose = (event) => {
      if (heartbeatIntervalRef.current) {
        clearInterval(heartbeatIntervalRef.current)
        heartbeatIntervalRef.current = null
      }
      console.log(
        '[WS] Connection closed — wasClean:', event.wasClean,
        '| code:', event.code,
        '| buildInProgress:', buildInProgressRef.current,
      )

      if (!event.wasClean && buildInProgressRef.current && isMountedRef.current) {
        reconnectAttemptsRef.current++
        if (reconnectAttemptsRef.current <= 5) {
          const delay = 1_000 * reconnectAttemptsRef.current
          console.log('[WS] Reconnecting in', delay, 'ms (attempt', reconnectAttemptsRef.current, ')')
          setTimeout(() => {
            if (isMountedRef.current && buildInProgressRef.current) {
              connectWebSocket()
            }
          }, delay)
        } else {
          console.error('[WS] Max reconnect attempts reached')
          if (isMountedRef.current) {
            setError('WebSocket connection lost after 5 retries')
            setStatus('failed')
          }
          buildInProgressRef.current = false
        }
      }
    }
  }, [taskId, mergePhaseResponse])

  // ── Start build ────────────────────────────────────────────────────────────
  const startBuild = useCallback(async () => {
    if (!taskId) {
      console.warn('[DockerBuild] startBuild called without taskId')
      return
    }
    if (buildInProgressRef.current) {
      console.log('[DockerBuild] SKIPPED DUPLICATE — buildInProgressRef already true')
      return
    }

    console.log('[DockerBuild] Starting build for task', taskId)
    buildInProgressRef.current = true
    setError(undefined)
    setWsParseError(undefined)
    setStatus('running')
    // Move any existing live logs to the replay history before starting fresh.
    setReplayLogs((prev) => [...prev, ...logs])
    setLogs([])
    setActiveSessionId(undefined)  // will be set by first session-tagged event
    setIsLive(true)
    setDurationSeconds(null)
    setFailureDiagnostics(null)

    try {
      const resp = await startDockerBuild(taskId)
      console.log('[DockerBuild] Build API response:', resp)
      if (isMountedRef.current) setImageTag(resp.image_tag ?? undefined)

      mergePhaseResponse({
        task_id: taskId,
        current_phase: 'docker_build_running',
        status: 'in_progress',
        artifacts: {},
        terraform_outputs: {},
        logs: [],
        message: '',
      })

      connectWebSocket()
    } catch (err) {
      const errorMsg = (err as Error).message
      console.error('[DockerBuild] Build start failed:', errorMsg)
      if (isMountedRef.current) {
        setError(errorMsg)
        setStatus('failed')
      }
      buildInProgressRef.current = false
      getDockerBuildStatus(taskId)
        .then((data) => {
          if (!isMountedRef.current) return
          if (data.logs) setLogs(data.logs as LogEntry[])
          setRetryCount(data.retries ?? 0)
          setBuildNumber(data.build_number ?? 1)
          setFailureDiagnostics({
            failure_reason: data.failure_reason ?? null,
            docker_command: data.docker_command ?? null,
            last_error_line: data.last_error_line ?? null,
            failed_step: data.failed_step ?? null,
          })
        })
        .catch(() => {})
    }
  }, [taskId, mergePhaseResponse, connectWebSocket])

  // ── Retry ──────────────────────────────────────────────────────────────────
  const handleRetry = useCallback(() => {
    if (currentPhase !== 'docker_build_failed' && currentPhase !== 'docker_build_success') {
      setError('Build not in retryable state. Please wait...')
      return
    }
    if (buildInProgressRef.current) {
      console.log('[DockerBuild] RETRY BLOCKED — build already in progress')
      return
    }
    console.log('[DockerBuild] MANUAL RETRY — phase:', currentPhase)
    cleanupWebSocket()
    setRetryCount((c) => c + 1)
    setStatus('retrying')
    setError(undefined)
    setWsParseError(undefined)
    setFailureDiagnostics(null)

    setTimeout(() => {
      buildInProgressRef.current = false
      startBuild()
    }, 500)
  }, [startBuild, currentPhase])

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full overflow-y-auto p-6 gap-5">

      {/* Context banner */}
      <div className={cn(
        'flex items-start gap-3 px-4 py-3 rounded-xl',
        'bg-blue-50 dark:bg-blue-500/10',
        'border border-blue-200 dark:border-blue-500/20',
      )}>
        <Container className="w-4 h-4 text-blue-600 dark:text-blue-400 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-medium text-blue-800 dark:text-blue-200">
            Docker Image Build
          </p>
          <p className="text-xs text-blue-700/70 dark:text-blue-400/60 mt-0.5">
            Building your Docker image locally using Docker Desktop. Logs stream in real time via WebSocket.
          </p>
        </div>
      </div>

      {/* WS parse error banner */}
      {wsParseError && (
        <div className={cn(
          'flex items-start gap-3 px-4 py-3 rounded-xl',
          'bg-orange-50 dark:bg-orange-500/10',
          'border border-orange-200 dark:border-orange-500/20',
        )}>
          <AlertCircle className="w-4 h-4 text-orange-600 dark:text-orange-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-semibold text-orange-700 dark:text-orange-300">WebSocket Parse Error</p>
            <p className="text-xs font-mono text-orange-600 dark:text-orange-400 mt-0.5 break-all">{wsParseError}</p>
          </div>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className={cn(
          'flex items-start gap-3 px-4 py-3 rounded-xl',
          'bg-red-50 dark:bg-red-500/10',
          'border border-red-200 dark:border-red-500/20',
        )}>
          <AlertCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
          <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
        </div>
      )}

      {/* Failure summary card */}
      {status === 'failed' && failureDiagnostics && (
        <div className={cn(
          'rounded-xl overflow-hidden border',
          'border-red-200 dark:border-red-500/30',
          'bg-white dark:bg-surface-900',
        )}>
          <div className={cn(
            'flex items-center gap-2 px-4 py-2.5',
            'bg-red-50 dark:bg-red-500/10 border-b border-red-200 dark:border-red-500/20',
          )}>
            <AlertTriangle className="w-4 h-4 text-red-600 dark:text-red-400" />
            <span className="text-sm font-semibold text-red-700 dark:text-red-300">Docker Build Failed</span>
          </div>
          <div className="px-4 py-3 space-y-2">
            {failureDiagnostics.failed_step && (
              <div className="flex items-start gap-2">
                <Terminal className="w-3.5 h-3.5 text-red-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-xs font-medium text-slate-500 dark:text-slate-400">Failed Step</p>
                  <p className="text-sm font-mono text-red-700 dark:text-red-300">{failureDiagnostics.failed_step}</p>
                </div>
              </div>
            )}
            {failureDiagnostics.failure_reason && !failureDiagnostics.failed_step && (
              <div className="flex items-start gap-2">
                <AlertTriangle className="w-3.5 h-3.5 text-red-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-xs font-medium text-slate-500 dark:text-slate-400">Reason</p>
                  <p className="text-sm font-mono text-red-700 dark:text-red-300">{failureDiagnostics.failure_reason}</p>
                </div>
              </div>
            )}
            {failureDiagnostics.last_error_line && (
              <div className="flex items-start gap-2">
                <span className="text-red-500 text-xs mt-0.5 shrink-0">✗</span>
                <div>
                  <p className="text-xs font-medium text-slate-500 dark:text-slate-400">Last Error</p>
                  <p className="text-sm font-mono text-red-600 dark:text-red-400 break-all">{failureDiagnostics.last_error_line}</p>
                </div>
              </div>
            )}
            {failureDiagnostics.docker_command && (
              <div className="flex items-start gap-2">
                <span className="text-slate-400 text-xs mt-0.5 shrink-0">$</span>
                <div>
                  <p className="text-xs font-medium text-slate-500 dark:text-slate-400">Command</p>
                  <p className="text-xs font-mono text-slate-600 dark:text-slate-400 break-all">{failureDiagnostics.docker_command}</p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Retry timeline */}
      {retryTimeline.length > 0 && (
        <div className={cn(
          'rounded-xl border border-slate-200 dark:border-white/[0.06]',
          'bg-white dark:bg-surface-900 px-4 py-3',
        )}>
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-2">
            Retry Timeline
          </p>
          <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
            {retryTimeline.map((entry, idx) => {
              const dot =
                entry.state === 'success' ? '🟢' :
                entry.state === 'failed'  ? '🔴' :
                entry.state === 'building' ? '🟡' : '⚪'
              const isActive = entry.execution_session_id === activeSessionId
              return (
                <div key={entry.execution_session_id ?? idx} className="flex items-center gap-1.5">
                  <span>{dot}</span>
                  <span className={cn(
                    'px-2 py-0.5 rounded-md border',
                    isActive
                      ? 'border-amber-500/40 bg-amber-500/10 text-amber-200'
                      : 'border-slate-200 dark:border-white/[0.06] text-slate-600 dark:text-slate-400',
                  )}>
                    Retry #{entry.retry_iteration} · {entry.state}
                  </span>
                  {idx < retryTimeline.length - 1 && <span className="text-slate-500">→</span>}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Live banner */}
      {isLive && status === 'running' && (
        <div className={cn(
          'flex items-center gap-2 px-4 py-2 rounded-lg',
          'bg-emerald-500/10 border border-emerald-500/25 text-emerald-300 text-xs font-medium',
        )}>
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          Streaming live retry execution…
          {activeSessionId && <span className="ml-auto font-mono text-emerald-400/60">session: {activeSessionId}</span>}
        </div>
      )}

      {/* Previous retry replay (collapsible) */}
      {replayLogs.length > 0 && (
        <details className="rounded-xl border border-slate-200 dark:border-white/[0.06] bg-white dark:bg-surface-900">
          <summary className="cursor-pointer select-none px-4 py-3 text-xs font-semibold uppercase tracking-widest text-slate-500 flex items-center gap-2">
            🟡 Previous Retry Logs (replay) · {replayLogs.length} entries
          </summary>
          <div className="border-t border-slate-200 dark:border-white/[0.06]">
            <BuildLogsPanel
              logs={replayLogs}
              status={'pending'}
              imageTag={undefined}
              retries={0}
              buildNumber={0}
              durationSeconds={null}
              autoScroll={false}
            />
          </div>
        </details>
      )}

      {/* Live build logs — current retry only */}
      <div className="relative">
        <BuildLogsPanel
          logs={logs}
          status={status}
          imageTag={imageTag}
          retries={retryCount}
          buildNumber={buildNumber}
          durationSeconds={durationSeconds}
          autoScroll
        />
      </div>

      {/* Action bar */}
      <div className="flex items-center justify-between pt-2">
        <button
          onClick={onBack}
          disabled={status === 'running'}
          className={cn(
            'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
            'border border-slate-200 dark:border-white/[0.06]',
            'text-slate-600 dark:text-slate-400',
            'hover:bg-slate-100 dark:hover:bg-white/[0.04]',
            'disabled:opacity-40 disabled:cursor-not-allowed',
          )}
        >
          Back
        </button>

        <div className="flex items-center gap-3">
          {(status === 'failed' || currentPhase === 'docker_build_failed') && (
            <button
              onClick={handleRetry}
              disabled={status === 'running' || status === 'retrying'}
              className={cn(
                'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                'border border-amber-300 dark:border-amber-500/30',
                'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300',
                'hover:bg-amber-100 dark:hover:bg-amber-500/20',
                (status === 'running' || status === 'retrying') && 'opacity-50 cursor-not-allowed',
              )}
            >
              <RefreshCw className={cn('w-3.5 h-3.5', status === 'retrying' && 'animate-spin')} />
              {status === 'retrying' ? 'Retrying...' : 'Retry Build'}
              {retryCount > 0 && status !== 'retrying' && (
                <span className="ml-1 text-xs text-amber-500">({retryCount})</span>
              )}
            </button>
          )}

          <button
            onClick={onContinue}
            disabled={status !== 'success' || currentPhase !== 'docker_build_success' || isPhaseLoading}
            className={cn(
              'flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-colors',
              status === 'success' && currentPhase === 'docker_build_success' && !isPhaseLoading
                ? 'bg-brand-600 hover:bg-brand-700 text-white'
                : 'bg-slate-200 dark:bg-surface-700 text-slate-400 dark:text-slate-500 cursor-not-allowed',
            )}
          >
            {isPhaseLoading ? 'Generating Terraform…' : 'Continue to Terraform'}
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
