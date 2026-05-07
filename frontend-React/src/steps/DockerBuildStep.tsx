import { useCallback, useEffect, useRef, useState } from 'react'
import { Container, RefreshCw, ChevronRight } from 'lucide-react'
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
  type?: 'done' | 'error'
  status?: string
}

// ── Props ──────────────────────────────────────────────────────────────────────

interface Props {
  /** Called when user clicks "Continue to Terraform" after a successful build */
  onContinue: () => void
  /** Called when user clicks "Back" */
  onBack: () => void
  /** Whether the Terraform phase is loading (disable continue button) */
  isPhaseLoading?: boolean
}

// ── Component ──────────────────────────────────────────────────────────────────

export function DockerBuildStep({ onContinue, onBack, isPhaseLoading }: Props) {
  const { taskId, currentPhase, mergePhaseResponse } = useWorkflowStore()

  const [logs, setLogs] = useState<LogEntry[]>([])
  const [status, setStatus] = useState<ExecutionStatus>('pending')
  const [imageTag, setImageTag] = useState<string>()
  const [error, setError] = useState<string>()
  const [retryCount, setRetryCount] = useState(0)

  const wsRef = useRef<WebSocket | null>(null)
  const startedRef = useRef(false)

  // ── Restore from DB on mount (page refresh) ────────────────────────────────
  useEffect(() => {
    if (!taskId) return

    // If phase is already past running, restore persisted logs from DB
    const alreadyDone = ['docker_build_success', 'docker_build_failed'].includes(currentPhase)
    if (alreadyDone) {
      getDockerBuildStatus(taskId)
        .then((data) => {
          setLogs((data.logs as LogEntry[]) ?? [])
          setStatus(data.status as ExecutionStatus)
          setImageTag(data.image_tag ?? undefined)
        })
        .catch(() => {})
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Start build + WebSocket ────────────────────────────────────────────────
  const startBuild = useCallback(async () => {
    if (!taskId) return
    startedRef.current = true
    setLogs([])
    setError(undefined)
    setStatus('running')

    try {
      // 1. Kick off the build on the backend
      const resp = await startDockerBuild(taskId)
      setImageTag(resp.image_tag ?? undefined)

      // Update workflow store phase
      mergePhaseResponse({
        task_id: taskId,
        current_phase: 'docker_build_running',
        status: 'in_progress',
        artifacts: {},
        terraform_outputs: {},
        logs: [],
        message: '',
      })

      // 2. Open WebSocket for live log streaming
      const wsUrl = getWsExecutionUrl(taskId)
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onmessage = (evt) => {
        try {
          const msg: WsMessage = JSON.parse(evt.data as string)

          if (msg.type === 'done') {
            const finalStatus: ExecutionStatus = msg.status === 'success' ? 'success' : 'failed'
            setStatus(finalStatus)
            mergePhaseResponse({
              task_id: taskId,
              current_phase: finalStatus === 'success' ? 'docker_build_success' : 'docker_build_failed',
              status: finalStatus === 'success' ? 'in_progress' : 'failed',
              artifacts: {},
              terraform_outputs: {},
              logs: [],
              message: '',
            })
            ws.close()
            return
          }

          if (msg.type === 'error') {
            setError(msg.message ?? 'WebSocket error')
            setStatus('failed')
            ws.close()
            return
          }

          // Regular log line
          if (msg.message) {
            setLogs((prev) => [
              ...prev,
              {
                timestamp: msg.timestamp ?? new Date().toISOString(),
                level: (msg.level ?? 'DEFAULT') as LogEntry['level'],
                message: msg.message!,
              },
            ])
          }
        } catch {
          // Ignore malformed messages
        }
      }

      ws.onerror = () => {
        setError('WebSocket connection error')
        setStatus('failed')
      }

      ws.onclose = () => {
        // Finalise status if still showing running
        setStatus((prev) => (prev === 'running' ? 'failed' : prev))
      }
    } catch (err) {
      setError((err as Error).message)
      setStatus('failed')
    }
  }, [taskId, mergePhaseResponse])

  // Auto-start build on mount (if phase is docker_completed and not yet started)
  useEffect(() => {
    if (!startedRef.current && currentPhase === 'docker_completed') {
      startBuild()
    }
    return () => {
      wsRef.current?.close()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Retry ──────────────────────────────────────────────────────────────────
  const handleRetry = useCallback(() => {
    wsRef.current?.close()
    startedRef.current = false
    setRetryCount((c) => c + 1)
    setStatus('retrying')

    setTimeout(() => {
      startBuild()
    }, 500)
  }, [startBuild])

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
            Building your Docker image locally using Docker Desktop. Logs stream in real time.
          </p>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className={cn(
          'flex items-start gap-3 px-4 py-3 rounded-xl',
          'bg-red-50 dark:bg-red-500/10',
          'border border-red-200 dark:border-red-500/20',
        )}>
          <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
        </div>
      )}

      {/* Live build logs */}
      <div className="relative">
        <BuildLogsPanel
          logs={logs}
          status={status}
          imageTag={imageTag}
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
          {/* Retry button — shown only after failure */}
          {status === 'failed' && (
            <button
              onClick={handleRetry}
              className={cn(
                'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                'border border-amber-300 dark:border-amber-500/30',
                'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300',
                'hover:bg-amber-100 dark:hover:bg-amber-500/20',
              )}
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Retry Build
              {retryCount > 0 && (
                <span className="ml-1 text-xs text-amber-500">({retryCount})</span>
              )}
            </button>
          )}

          {/* Continue — enabled only after success */}
          <button
            onClick={onContinue}
            disabled={status !== 'success' || isPhaseLoading}
            className={cn(
              'flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-colors',
              status === 'success' && !isPhaseLoading
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
