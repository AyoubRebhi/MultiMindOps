const BASE =
  (import.meta as unknown as { env: { VITE_API_BASE_URL?: string } }).env
    .VITE_API_BASE_URL ?? ''

// ── Domain types ───────────────────────────────────────────────────────────────

export interface CorrectorFix {
  title: string
  explanation: string
  patch: string
  severity: 'high' | 'medium' | 'low'
  applies_to: string
}

export interface CorrectorAnalysis {
  status?: string
  error_type?: string
  root_cause?: string
  confidence?: number
  failed_step?: string
  error_excerpt?: string
  retry_recommended?: boolean
  fixes?: CorrectorFix[]
}

export interface CorrectorState {
  status: string
  retry_count: number
  max_retries: number
  analysis?: CorrectorAnalysis
  error?: string
  started_at?: string
  finished_at?: string
}

export interface CorrectorStatusResponse {
  task_id: string
  current_phase: string
  corrector: CorrectorState
  retry_count: number
  max_retries: number
  analysis?: CorrectorAnalysis
}

export interface ReanalyzeResponse {
  task_id: string
  status: string
  message: string
}

// ── API calls ──────────────────────────────────────────────────────────────────

export async function getCorrectorAnalysis(
  taskId: string,
): Promise<CorrectorStatusResponse> {
  const res = await fetch(`${BASE}/api/corrector/${taskId}`)
  if (!res.ok) {
    const d = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(d.detail ?? `Corrector fetch failed: ${res.status}`)
  }
  return res.json()
}

export async function reanalyze(taskId: string): Promise<ReanalyzeResponse> {
  const res = await fetch(`${BASE}/api/corrector/reanalyze/${taskId}`, {
    method: 'POST',
  })
  if (!res.ok) {
    const d = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(d.detail ?? `Reanalyze failed: ${res.status}`)
  }
  return res.json()
}

// ── Phase helpers ──────────────────────────────────────────────────────────────

const CORRECTOR_PHASES = new Set([
  'docker_build_failed',
  'corrector_analysis_running',
  'corrector_analysis_completed',
  'human_review_required',
  'execution_failed',
])

export function isCorrectorPhase(phase: string): boolean {
  return CORRECTOR_PHASES.has(phase)
}

export function isAnalysisRunning(phase: string): boolean {
  return phase === 'corrector_analysis_running'
}

export function isExecutionFailed(phase: string): boolean {
  return phase === 'execution_failed'
}

export function canRetryBuild(retryCount: number, maxRetries: number): boolean {
  return retryCount < maxRetries
}
