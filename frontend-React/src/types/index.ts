// ─── Task statuses ────────────────────────────────────────────────────────────
export type TaskStatus =
  | 'pending'
  | 'in_progress'
  | 'completed'
  | 'failed'
  | 'awaiting_human_review'
  | 'human_approved'
  | 'human_approved_with_changes'

// ─── Request schemas ──────────────────────────────────────────────────────────
export interface TaskCreate {
  prompt: string
  repo_url?: string
  repository_visibility?: 'public' | 'private'
  github_token?: string
}

export interface PlanPreviewRequest {
  prompt: string
  repo_url: string
  repository_visibility?: string
  github_token?: string
}

export interface GenerateArtifactsRequest {
  prompt: string
  repo_url: string
  repository_visibility?: string
  github_token?: string
  approved_artifacts?: string[]
}

export interface ReviewArtifactsRequest {
  reviewed_artifacts: Record<string, string>
  review_notes?: string
}

// ─── Domain models ────────────────────────────────────────────────────────────
export interface LogEntry {
  step?: string
  agent?: string
  message?: string
  level?: 'info' | 'warning' | 'error' | 'success' | 'debug'
  timestamp?: string
  details?: unknown
  [key: string]: unknown
}

export interface PlanAction {
  type?: string
  description?: string
  artifact?: string
  agent?: string
  priority?: number
  [key: string]: unknown
}

export interface PlanData {
  summary?: string
  actions?: PlanAction[]
  artifacts?: string[]
  technologies?: string[]
  estimated_steps?: number
  [key: string]: unknown
}

export interface Vulnerability {
  id?: string
  severity?: 'critical' | 'high' | 'medium' | 'low' | 'info'
  title?: string
  description?: string
  file?: string
  line?: number
  cve?: string
  recommendation?: string
}

export interface EnvSecurity {
  exposed_secrets?: string[]
  issues?: string[]
  score?: number
  has_env_file?: boolean
}

export interface SecurityAnalysis {
  score?: number
  grade?: string
  vulnerabilities?: Vulnerability[]
  recommendations?: string[]
  env_security?: EnvSecurity
  summary?: string
  critical?: number
  high?: number
  medium?: number
  low?: number
  [key: string]: unknown
}

export interface DiffEntry {
  before?: string
  after?: string
  filename?: string
  changes?: number
}

export interface TaskResult {
  artifacts?: Record<string, string>
  diffs?: Record<string, DiffEntry>
  security?: SecurityAnalysis
  cicd?: Record<string, string>
  summary?: string
  repo_summary?: unknown
  [key: string]: unknown
}

// ─── API response schemas ──────────────────────────────────────────────────────
export interface TaskResponse {
  id: string
  prompt: string
  status: TaskStatus
  plan?: PlanData
  logs: LogEntry[]
  result?: TaskResult
  error_message?: string
  created_at: string
  updated_at: string
}

export interface PlanPreviewResponse {
  status: string
  plan?: PlanData
  repository_security?: SecurityAnalysis
  repo_summary?: unknown
  logs: LogEntry[]
}

// ─── UI helpers ───────────────────────────────────────────────────────────────
export interface StepState {
  step: 'form' | 'plan' | 'generating' | 'review' | 'result'
  planPreview?: PlanPreviewResponse
  formData?: PlanPreviewRequest
  task?: TaskResponse
  envFile?: File
}
