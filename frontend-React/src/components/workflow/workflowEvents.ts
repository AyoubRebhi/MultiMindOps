/**
 * Workflow event → intent → state-transition mapping layer.
 *
 * This is the SINGLE place that knows how a backend event (WebSocket frame or
 * API response) translates into a UI workflow-phase transition. Components must
 * never interpret raw events themselves — they go through `mapWsEvent` so there
 * is exactly one definition of "DOCKER_BUILD_SUCCESS → DOCKER_BUILD = completed".
 *
 * Backend stays the source of truth: these intents drive *optimistic* reactive
 * state, and every terminal event also emits a `reconcile` intent so the engine
 * re-fetches authoritative server state.
 */

// ── Vocabulary ──────────────────────────────────────────────────────────────

/** Canonical phase-status vocabulary shared by the engine and every renderer. */
export type PhaseStatus =
  | 'completed'
  | 'failed'
  | 'running'
  | 'awaiting_input'
  | 'not_started'

/**
 * The execution streams the backend exposes over WebSockets. Each maps to
 * exactly one workflow phase whose status it drives.
 *   - docker_build       → /ws/execution/{taskId}
 *   - terraform_validate → /ws/terraform/{taskId}/terraform_validate
 *   - terraform_plan     → /ws/terraform/{taskId}/terraform_plan
 */
export type StreamKind = 'docker_build' | 'terraform_validate' | 'terraform_plan'

/**
 * Phase keys the engine tracks. These match the uppercase keys the backend
 * writes into `Workflow.phases_state`, plus the synthetic `DOCKER_BUILD` overlay
 * for the image-build sub-state (which the backend keeps in
 * `execution.docker`, not in `phases_state`).
 */
export type EnginePhaseKey =
  | 'ARCHITECTURE_DECISION'
  | 'PLAN_SELECTED'
  | 'DOCKER'
  | 'DOCKER_BUILD'
  | 'TERRAFORM_GENERATION'
  | 'TERRAFORM_VALIDATION'
  | 'TERRAFORM_PLAN'
  | 'TERRAFORM'
  | 'KUBERNETES'
  | 'CICD'
  | 'VALIDATION'

/** Stream → the phase whose status it drives. */
export const STREAM_TO_PHASE: Record<StreamKind, EnginePhaseKey> = {
  docker_build: 'DOCKER_BUILD',
  terraform_validate: 'TERRAFORM_VALIDATION',
  terraform_plan: 'TERRAFORM_PLAN',
}

// ── Phase-state shape (generic; UI panels narrow it as needed) ───────────────

export interface PhaseEntry {
  status?: string
  updated_at?: string
  task_id?: string
  // Phases may carry extra payload (e.g. infrastructure_summary). Kept open so
  // the merge preserves whatever the backend attached.
  [key: string]: unknown
}
export type PhasesState = Record<string, PhaseEntry>

// ── Raw event shape (identical protocol on both WS endpoints) ────────────────

export interface WorkflowWsEvent {
  type?: 'log' | 'complete' | 'error' | 'info' | 'pong' | string
  status?: string // 'success' | 'failed' on `complete`
  message?: string
  level?: string
  is_replay?: boolean
  exit_code?: number | null
}

// ── Intents (the normalized output the reducer applies) ──────────────────────

export type WorkflowIntent =
  | { kind: 'phase_status'; phase: EnginePhaseKey; status: PhaseStatus }
  | { kind: 'phase_log'; phase: EnginePhaseKey; line: string; replay?: boolean }
  /** Terminal event → engine should re-fetch authoritative server state. */
  | { kind: 'reconcile' }

/**
 * The ONE mapping function. Translates a raw WS frame on a given stream into a
 * normalized list of workflow intents. Pure, side-effect free, fully reusable.
 *
 *   log (live)  → phase running + append line
 *   log (replay)→ append line only (history, no status change)
 *   complete    → phase completed/failed + reconcile
 *   error       → append line + phase failed + reconcile
 *   pong / info → ignored
 */
export function mapWsEvent(stream: StreamKind, evt: WorkflowWsEvent): WorkflowIntent[] {
  const phase = STREAM_TO_PHASE[stream]
  const t = evt.type

  if (t === 'pong' || t === 'info') return []

  if (t === 'complete') {
    return [
      { kind: 'phase_status', phase, status: evt.status === 'success' ? 'completed' : 'failed' },
      { kind: 'reconcile' },
    ]
  }

  if (t === 'error') {
    return [
      { kind: 'phase_log', phase, line: `ERROR: ${evt.message ?? 'unknown'}` },
      { kind: 'phase_status', phase, status: 'failed' },
      { kind: 'reconcile' },
    ]
  }

  // 'log' or an untyped bare line.
  if (evt.message != null) {
    const out: WorkflowIntent[] = []
    if (!evt.is_replay) out.push({ kind: 'phase_status', phase, status: 'running' })
    out.push({ kind: 'phase_log', phase, line: evt.message, replay: evt.is_replay })
    return out
  }

  return []
}

// ── Status normalizers (server / build sub-state → engine vocabulary) ────────

/** Map a `phases_state` status string → engine `PhaseStatus`. */
export function normalizeServerStatus(v: string | undefined): PhaseStatus {
  // DOCKER may finish via deterministic fallback (LLM unavailable). That is a
  // successful completion for workflow-progression purposes — the build step
  // can run on the fallback artifacts. The fallback distinction is carried
  // separately on the phase entry (used_llm / fallback_used / generation_mode).
  if (v === 'completed_with_fallback') return 'completed'
  if (v === 'completed' || v === 'failed' || v === 'running' || v === 'awaiting_input') return v
  return 'not_started'
}

/** Map a Docker build sub-status (`execution.docker.status`) → `PhaseStatus`. */
export function normalizeBuildStatus(v: string | undefined): PhaseStatus {
  if (v === 'success') return 'completed'
  if (v === 'failed') return 'failed'
  if (v === 'running') return 'running'
  return 'not_started'
}

/**
 * Merge authoritative server status with an optimistic overlay status.
 *
 * Backend wins whenever it has reached a terminal state (completed/failed) —
 * this guarantees the backend remains the source of truth after any refresh.
 * The overlay only fills the gap while the server is still catching up
 * (e.g. show `running` the instant a build starts, before the next poll).
 */
export function mergeStatus(server: PhaseStatus, overlay: PhaseStatus | undefined): PhaseStatus {
  if (server === 'completed' || server === 'failed') return server
  if (overlay) return overlay
  return server
}
