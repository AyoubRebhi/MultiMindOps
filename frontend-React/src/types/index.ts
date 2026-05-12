// ─── Task statuses ────────────────────────────────────────────────────────────
export type TaskStatus =
  | 'pending'
  | 'in_progress'
  | 'completed'
  | 'failed'
  | 'awaiting_human_review'
  | 'human_approved'
  | 'human_approved_with_changes'

// ─── Pipeline step status ─────────────────────────────────────────────────────
export type PipelineStepStatus = 'pending' | 'running' | 'completed' | 'failed'

// ─── Terraform outputs contract (consumed by KubernetesAgent) ─────────────────
export interface TerraformOutputs {
  cluster_endpoint?: string
  cluster_name?: string
  load_balancer_dns?: string
  ecr_repository_url?: string
  vpc_id?: string
  subnet_ids?: string
  security_group_id?: string
  rds_endpoint?: string
  [key: string]: string | undefined
}

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
  // Normalized (frontend-friendly) fields
  summary?: string
  actions?: PlanAction[]
  artifacts?: string[]
  technologies?: string[]
  estimated_steps?: number
  // Backend planner field names (used for normalization)
  reasoning_summary?: string
  steps?: string[]
  required_artifacts?: string[]
  plan_variant?: string
  plan_score?: number
  plan_description?: string
  estimated_complexity?: string
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

export interface ValidationResult {
  status?: 'valid' | 'partial' | 'invalid'
  missing_artifacts?: string[]
  quality_issues?: string[]
  warnings?: string[]
  required_artifacts?: string[]
  generated_artifacts?: string[]
  requested_artifacts?: string[]
}

export interface HumanReview {
  status?: 'awaiting_review' | 'approved' | 'approved_with_changes'
  original_artifacts?: Record<string, string>
  reviewed_artifacts?: Record<string, string>
  changed_artifacts?: string[]
  review_notes?: string | null
  reviewed_at?: string | null
}

export interface InfrastructureResult {
  artifacts?: Record<string, string>
  [key: string]: unknown
}

export interface TaskResult {
  // Legacy flat path (may not exist — use infrastructure.artifacts instead)
  artifacts?: Record<string, string>
  diffs?: Record<string, DiffEntry>
  security?: SecurityAnalysis
  cicd?: Record<string, string>
  summary?: string
  repo_summary?: unknown
  // Correct nested paths from backend
  infrastructure?: InfrastructureResult
  validation?: ValidationResult
  human_review?: HumanReview
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
  // New top-level fields from multi-agent backend (V3)
  infra?: InfrastructureResult
  terraform_outputs?: TerraformOutputs
  validation?: ValidationResult
  cicd?: Record<string, string>
  cost_estimation?: { monthly_cost?: number; cost_profile?: string; [key: string]: unknown }
  error_message?: string
  created_at: string
  updated_at: string
}

export interface PlanPreviewResponse {
  status: string
  task_id?: string
  requires_user_input?: boolean
  plan?: PlanData
  /** Raw scan output from RepositorySecurityService — has risk_score, not score */
  repository_security?: Record<string, unknown>
  /** Transformed SecurityAnalysis ready for SecurityScore component */
  security?: SecurityAnalysis
  repo_summary?: unknown
  logs: LogEntry[]
}

// ─── Architecture Decision types ──────────────────────────────────────────────
export interface ArchitecturePlan {
  id: string                          // "low_cost" | "balanced" | "high_performance"
  title: string
  description: string
  tradeoffs: string[]
  scalability_tier: string
  availability_level: string
  monthly_cost: number
  yearly_cost: number
  cost_breakdown: Record<string, number>
  cost_profile: string                // "startup" | "small_production" | ...
  optimization_tips: string[]
  assumptions: string[]
  pricing_model_version: string
  infrastructure: Record<string, unknown>
  aws_services: string[]
  // Underlying planner data for the generation phase
  plan?: PlanData
  required_artifacts?: string[]
  reasoning_summary?: string
  estimated_complexity?: string
  steps?: string[]
}

export interface ArchitectureDecision {
  plans: ArchitecturePlan[]
  recommended_plan: string            // "balanced"
}

// ─── Plan validation ───────────────────────────────────────────────────────────
export type PlanValidationDecision = 'approved' | 'rejected' | 'modified'

export interface ValidatePlanRequest {
  task_id: string
  decision: PlanValidationDecision
  feedback?: string | null
}

export interface ValidatePlanResponse {
  status: string
  task_id: string
  decision: PlanValidationDecision
  plan?: PlanData
  requires_user_input?: boolean
  message?: string
  logs?: LogEntry[]
}

// ─── UI helpers ───────────────────────────────────────────────────────────────
export interface StepState {
  step: 'form' | 'plan' | 'plan_validation' | 'generating' | 'review' | 'result'
  planPreview?: PlanPreviewResponse
  formData?: PlanPreviewRequest
  task?: TaskResponse
  envFile?: File
}
