/**
 * Reactive workflow engine.
 *
 * Hybrid model:
 *   • Backend = source of truth. `workflow.phases_state` (server) is authoritative
 *     and always wins after a refresh/reload.
 *   • Frontend = reactive engine. WebSocket events are interpreted through the
 *     single `mapWsEvent` mapping layer and applied as an *optimistic overlay*
 *     so the UI transitions in real time; every terminal event triggers a
 *     reconcile (re-fetch) so the overlay is replaced by server truth.
 *
 * All WebSocket connections, API calls, and event interpretation live HERE.
 * Workflow UI components consume the returned state and are pure renderers.
 */
import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react'
import { useRunPhase, useRefreshProjectWorkflows } from '@/hooks/useProjects'
import {
  getWsTerraformUrl,
  getWsExecutionUrl,
  startDockerBuild,
  getDockerBuildStatus,
  BuildBlockedError,
  type DockerBuildBlocked,
} from '@/services/workflowApi'
import { tokenStorage } from '@/lib/tokenStorage'
import type { PhaseName, WorkflowResponse } from '@/types/project'
import {
  mapWsEvent,
  mergeStatus,
  normalizeBuildStatus,
  normalizeServerStatus,
  STREAM_TO_PHASE,
  type EnginePhaseKey,
  type PhaseStatus,
  type PhasesState,
  type StreamKind,
  type WorkflowIntent,
  type WorkflowWsEvent,
} from './workflowEvents'

const MAX_LOG_LINES = 2000

// ── Overlay reducer ──────────────────────────────────────────────────────────

interface BuildMeta {
  imageTag?: string
  durationSeconds: number | null
  finishedAt: string | null
  failureReason: string | null
}

interface OverlayState {
  /** Optimistic per-phase status overrides (until the server catches up). */
  status: Partial<Record<EnginePhaseKey, PhaseStatus>>
  /** Live log buffers, keyed by the phase a stream drives. */
  logs: Partial<Record<EnginePhaseKey, string[]>>
  build: BuildMeta
  buildLive: boolean
  buildStarting: boolean
  buildError: string | null
  /** Structured PrebuildGate rejection (HTTP 422). When set, the build did NOT
   *  start and no WebSocket was opened — the UI shows WHY it was blocked. */
  buildBlocked: DockerBuildBlocked | null
}

const INITIAL_OVERLAY: OverlayState = {
  status: {},
  logs: {},
  build: { imageTag: undefined, durationSeconds: null, finishedAt: null, failureReason: null },
  buildLive: false,
  buildStarting: false,
  buildError: null,
  buildBlocked: null,
}

type OverlayAction =
  | { type: 'intent'; intent: Extract<WorkflowIntent, { kind: 'phase_status' | 'phase_log' }> }
  | { type: 'set_status'; phase: EnginePhaseKey; status: PhaseStatus }
  | { type: 'clear_logs'; phase: EnginePhaseKey }
  | { type: 'set_build_meta'; meta: Partial<BuildMeta> }
  | { type: 'set_build_live'; live: boolean }
  | { type: 'set_build_starting'; starting: boolean }
  | { type: 'set_build_error'; error: string | null }
  | { type: 'set_build_blocked'; blocked: DockerBuildBlocked | null }
  | { type: 'restore_build'; status: PhaseStatus; meta: BuildMeta; logs: string[]; live: boolean }

function appendLog(buf: string[] | undefined, line: string): string[] {
  const next = buf ? [...buf, line] : [line]
  return next.length > MAX_LOG_LINES ? next.slice(next.length - MAX_LOG_LINES) : next
}

function reducer(state: OverlayState, action: OverlayAction): OverlayState {
  switch (action.type) {
    case 'intent': {
      const intent = action.intent
      if (intent.kind === 'phase_status') {
        return { ...state, status: { ...state.status, [intent.phase]: intent.status } }
      }
      // phase_log
      return {
        ...state,
        logs: { ...state.logs, [intent.phase]: appendLog(state.logs[intent.phase], intent.line) },
      }
    }
    case 'set_status':
      return { ...state, status: { ...state.status, [action.phase]: action.status } }
    case 'clear_logs':
      return { ...state, logs: { ...state.logs, [action.phase]: [] } }
    case 'set_build_meta':
      return { ...state, build: { ...state.build, ...action.meta } }
    case 'set_build_live':
      return { ...state, buildLive: action.live }
    case 'set_build_starting':
      return { ...state, buildStarting: action.starting }
    case 'set_build_error':
      return { ...state, buildError: action.error }
    case 'set_build_blocked':
      return { ...state, buildBlocked: action.blocked }
    case 'restore_build':
      return {
        ...state,
        status: { ...state.status, DOCKER_BUILD: action.status },
        logs: { ...state.logs, DOCKER_BUILD: action.live ? [] : action.logs },
        build: action.meta,
        buildLive: action.live,
      }
    default:
      return state
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function errorMessage(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail ?? (e as Error)?.message ?? 'Request failed'
}

// ── Engine hook ────────────────────────────────────────────────────────────

export function useWorkflowEngine(
  projectId: string,
  workflow: WorkflowResponse,
  canRun: boolean,
) {
  const serverPhases = (workflow.phases_state ?? {}) as PhasesState
  const taskId = (serverPhases['ARCHITECTURE_DECISION']?.task_id as string | undefined) ?? null

  const runPhaseMut = useRunPhase(projectId, workflow.id)
  const refresh = useRefreshProjectWorkflows(projectId)
  const refreshRef = useRef(refresh)
  refreshRef.current = refresh

  const [overlay, dispatch] = useReducer(reducer, INITIAL_OVERLAY)

  // Merged, authoritative-first status for a single phase.
  const statusOf = useCallback(
    (phase: EnginePhaseKey): PhaseStatus =>
      mergeStatus(
        normalizeServerStatus(serverPhases[phase]?.status as string | undefined),
        overlay.status[phase],
      ),
    [serverPhases, overlay.status],
  )

  // Drop-in replacement for the raw `phases_state`: same shape, but with the
  // optimistic overlay + synthetic DOCKER_BUILD phase folded in. Every renderer
  // reads this single object.
  const phases: PhasesState = useMemo(() => {
    const out: PhasesState = { ...serverPhases }
    ;(Object.keys(overlay.status) as EnginePhaseKey[]).forEach((key) => {
      const merged = mergeStatus(
        normalizeServerStatus(out[key]?.status as string | undefined),
        overlay.status[key],
      )
      out[key] = { ...(out[key] ?? {}), status: merged }
    })
    if (out.DOCKER_BUILD && overlay.build.finishedAt) {
      out.DOCKER_BUILD = { ...out.DOCKER_BUILD, updated_at: overlay.build.finishedAt }
    }
    return out
  }, [serverPhases, overlay.status, overlay.build.finishedAt])

  const logsOf = useCallback(
    (phase: EnginePhaseKey): string[] => overlay.logs[phase] ?? [],
    [overlay.logs],
  )

  // Which Terraform stream (if any) is currently live, derived from merged state.
  const terraformActive: StreamKind | null =
    statusOf('TERRAFORM_VALIDATION') === 'running'
      ? 'terraform_validate'
      : statusOf('TERRAFORM_PLAN') === 'running'
        ? 'terraform_plan'
        : null

  // Apply a list of intents from the mapping layer; route reconciles to refetch.
  const applyIntents = useCallback((intents: WorkflowIntent[]) => {
    for (const intent of intents) {
      if (intent.kind === 'reconcile') refreshRef.current()
      else dispatch({ type: 'intent', intent })
    }
  }, [])

  // ── Terraform live stream ─────────────────────────────────────────────────
  useEffect(() => {
    if (!taskId || !terraformActive) return
    const phaseKey = STREAM_TO_PHASE[terraformActive]
    dispatch({ type: 'clear_logs', phase: phaseKey })
    const ws = new WebSocket(getWsTerraformUrl(taskId, terraformActive, tokenStorage.getAccess()))
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
    }, 30_000)
    ws.onmessage = (evt) => {
      try {
        applyIntents(mapWsEvent(terraformActive, JSON.parse(evt.data as string)))
      } catch {
        /* ignore malformed frame */
      }
    }
    ws.onclose = () => clearInterval(ping)
    return () => {
      clearInterval(ping)
      try { ws.close() } catch { /* noop */ }
    }
  }, [taskId, terraformActive, applyIntents])

  // ── Docker build live stream ──────────────────────────────────────────────
  useEffect(() => {
    if (!taskId || !overlay.buildLive) return
    const ws = new WebSocket(getWsExecutionUrl(taskId, tokenStorage.getAccess()))
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
    }, 30_000)
    ws.onmessage = (evt) => {
      let msg: WorkflowWsEvent
      try {
        msg = JSON.parse(evt.data as string)
      } catch {
        return
      }
      if (msg.type === 'complete' || msg.type === 'error') {
        // Stream settled — stop the live socket and pull authoritative meta.
        dispatch({ type: 'set_build_live', live: false })
        getDockerBuildStatus(taskId)
          .then((d) =>
            dispatch({
              type: 'set_build_meta',
              meta: {
                imageTag: d.image_tag ?? undefined,
                durationSeconds: d.duration_seconds ?? null,
                finishedAt: d.finished_at ?? null,
                failureReason: d.failure_reason ?? d.last_error_line ?? null,
              },
            }),
          )
          .catch(() => {})
      }
      applyIntents(mapWsEvent('docker_build', msg))
    }
    ws.onclose = () => clearInterval(ping)
    return () => {
      clearInterval(ping)
      try { ws.close() } catch { /* noop */ }
    }
  }, [taskId, overlay.buildLive, applyIntents])

  // ── Restore persisted Docker build state (survives refresh) ───────────────
  useEffect(() => {
    if (!taskId) return
    let cancelled = false
    getDockerBuildStatus(taskId)
      .then((d) => {
        if (cancelled) return
        const status = normalizeBuildStatus(d.status)
        if (status === 'not_started') return
        dispatch({
          type: 'restore_build',
          status,
          meta: {
            imageTag: d.image_tag ?? undefined,
            durationSeconds: d.duration_seconds ?? null,
            finishedAt: d.finished_at ?? null,
            failureReason: d.failure_reason ?? d.last_error_line ?? null,
          },
          logs: Array.isArray(d.logs)
            ? (d.logs as Array<{ message?: string }>).map((l) => l.message ?? '')
            : [],
          live: status === 'running' || d.current_phase === 'docker_build_running',
        })
      })
      .catch(() => {
        /* no build yet — leave as Not Started */
      })
    return () => {
      cancelled = true
    }
  }, [taskId])

  // ── Actions (the only place components trigger state changes) ──────────────

  const runPhase = useCallback(
    (phase: PhaseName) => {
      // Optimistic transition for instant feedback; server reconciles on refetch.
      dispatch({ type: 'set_status', phase: phase as EnginePhaseKey, status: 'running' })
      runPhaseMut.mutate(phase, {
        onError: () =>
          dispatch({ type: 'set_status', phase: phase as EnginePhaseKey, status: 'failed' }),
      })
    },
    [runPhaseMut],
  )

  const startBuild = useCallback(async () => {
    if (!taskId) return
    dispatch({ type: 'set_build_error', error: null })
    dispatch({ type: 'set_build_blocked', blocked: null })
    dispatch({ type: 'set_build_starting', starting: true })
    dispatch({ type: 'clear_logs', phase: 'DOCKER_BUILD' })
    dispatch({ type: 'set_build_meta', meta: { failureReason: null } })
    try {
      await startDockerBuild(taskId)
      dispatch({ type: 'set_status', phase: 'DOCKER_BUILD', status: 'running' })
      dispatch({ type: 'set_build_live', live: true })
    } catch (e) {
      // Blocked (HTTP 422): the build never started and there is NO stream to
      // open. Surface the structured reason instead of a generic error and do
      // NOT flip buildLive — that would connect the WS to a dead stream.
      if (e instanceof BuildBlockedError) {
        dispatch({ type: 'set_build_blocked', blocked: e.blocked })
      } else {
        dispatch({ type: 'set_build_error', error: errorMessage(e) })
      }
    } finally {
      dispatch({ type: 'set_build_starting', starting: false })
    }
  }, [taskId])

  /** Recovery for the 409 "current phase: terraform_completed" build gate: a
   *  fresh Docker generation resets the backing task's cursor to docker_completed
   *  so the build endpoint accepts the request again. */
  const regenerateDocker = useCallback(() => {
    dispatch({ type: 'set_build_error', error: null })
    dispatch({ type: 'set_build_blocked', blocked: null })
    runPhase('DOCKER' as PhaseName)
  }, [runPhase])

  const clearBuildError = useCallback(() => dispatch({ type: 'set_build_error', error: null }), [])
  const clearBuildBlocked = useCallback(
    () => dispatch({ type: 'set_build_blocked', blocked: null }),
    [],
  )

  const build = {
    status: statusOf('DOCKER_BUILD'),
    imageTag: overlay.build.imageTag,
    durationSeconds: overlay.build.durationSeconds,
    finishedAt: overlay.build.finishedAt,
    failureReason: overlay.build.failureReason,
    live: overlay.buildLive,
    starting: overlay.buildStarting,
    error: overlay.buildError,
    blocked: overlay.buildBlocked,
    logs: logsOf('DOCKER_BUILD'),
  }

  return {
    taskId,
    phases,
    statusOf,
    logsOf,
    terraformActive,
    build,
    canRun,
    runPhase,
    startBuild,
    regenerateDocker,
    clearBuildError,
    clearBuildBlocked,
    runPhasePending: runPhaseMut.isPending,
    runPhaseError: runPhaseMut.error,
    runPhaseVariable: runPhaseMut.variables,
  }
}

export type WorkflowEngine = ReturnType<typeof useWorkflowEngine>
