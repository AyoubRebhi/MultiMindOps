// ─── Project-centric domain types ────────────────────────────────────────────

export type ProjectRole =
  | 'OWNER'
  | 'DEVELOPER'
  | 'CLOUD_ARCHITECT'
  | 'ADMIN'
  | 'VIEWER'

export type ProjectStatus = 'draft' | 'active' | 'archived' | 'failed'

export type StrategyTier = 'minimal' | 'balanced' | 'robust'

export type ArchitectureType =
  | 'monolith'
  | 'microservices'
  | 'serverless'
  | 'static_site'
  | 'data_pipeline'
  | 'other'

export type RepositoryVisibility = 'public' | 'private'

// Kept in sync with backend ProjectBootstrapStatus and the state machine in
// project_bootstrap_service.py. Frontend should render distinct progress UI
// for each value.
export type ProjectBootstrapStatus =
  | 'pending'
  | 'analyzing'
  | 'context_building'
  | 'ready'
  | 'failed'

export type WorkflowExecutionMode = 'full' | 'phase' | 'replay'

export type WorkflowStatus =
  | 'pending'
  | 'running'
  | 'awaiting_input'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type ArtifactValidationStatus =
  | 'pending'
  | 'passed'
  | 'failed'
  | 'skipped'

export interface ProjectCreatePayload {
  // The new minimal create form sends only these three. Legacy classifiers
  // (architecture_type / application_profile / default_strategy_tier) remain
  // valid request fields for backwards-compatible callers but the AI
  // bootstrap infers them when omitted.
  name: string
  repository_url?: string
  repository_visibility?: RepositoryVisibility
  description?: string
  architecture_type?: ArchitectureType
  application_profile?: string
  default_strategy_tier?: StrategyTier
}

export interface ProjectUpdatePayload {
  name?: string
  description?: string
  repository_url?: string
  repository_visibility?: RepositoryVisibility
  architecture_type?: ArchitectureType
  application_profile?: string
  default_strategy_tier?: StrategyTier
  current_status?: ProjectStatus
}

export interface ProjectResponse {
  id: string
  owner_id: string
  name: string
  description?: string | null
  repository_url?: string | null
  repository_visibility?: string | null
  architecture_type?: string | null
  application_profile?: string | null
  default_strategy_tier?: string | null
  current_status: ProjectStatus
  bootstrap_status: ProjectBootstrapStatus
  bootstrap_error?: string | null
  project_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface WorkflowResponse {
  id: string
  project_id: string
  started_by?: string | null
  current_phase?: string | null
  status: WorkflowStatus
  execution_mode: WorkflowExecutionMode
  phases_state: Record<string, unknown>
  error_message?: string | null
  created_at: string
  finished_at?: string | null
  updated_at: string
}

export type ApprovalState =
  | 'pending_review'
  | 'approved'
  | 'rejected'
  | 'requires_changes'

export type ApprovalAction = 'approve' | 'reject' | 'request_changes'

export interface ArtifactResponse {
  id: string
  project_id: string
  workflow_id?: string | null
  artifact_type: string
  artifact_subtype: string
  content: string
  validation_status: ArtifactValidationStatus
  approval_state: ApprovalState
  generated_by_agent?: string | null
  approved_by?: string | null
  version: number
  artifact_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ArtifactApprovalResponse {
  id: string
  artifact_id: string
  approved_by: string
  action: ApprovalAction
  comment?: string | null
  created_at: string
}

export interface ProjectContextResponse {
  id: string
  project_id: string
  context_type: string
  content: Record<string, unknown>
  generated_by?: string | null
  embedding_reference?: string | null
  created_at: string
  updated_at: string
}

export interface IdentityResponse {
  id: string
  email: string
  display_name?: string | null
  memberships: { project_id: string; role: ProjectRole }[]
}

export interface ArchitectureDecisionResponse {
  workflow_id: string
  current_phase?: string | null
  status: string
  selected_plan_id?: string | null
  plans: Array<{
    id: string
    title: string
    description: string
    tradeoffs: string[]
    scalability_tier: string
    availability_level: string
    monthly_cost: number
    yearly_cost: number
    cost_breakdown: Record<string, number>
    cost_profile: string
    optimization_tips: string[]
    assumptions: string[]
    pricing_model_version: string
    infrastructure: Record<string, unknown>
    aws_services: string[]
    required_artifacts?: string[]
    reasoning_summary?: string
  }>
  recommended_plan: string
}

export interface ProjectMemberResponse {
  id: string
  project_id: string
  user_id: string
  role: ProjectRole
  created_at: string
}

export interface ProjectDetailResponse extends ProjectResponse {
  members: ProjectMemberResponse[]
  workflows: WorkflowResponse[]
  artifact_count: number
}

// ─── Workflow execution payloads ─────────────────────────────────────────────

export type PhaseName = 'DOCKER' | 'TERRAFORM' | 'KUBERNETES' | 'CICD'

export interface StartWorkflowPayload {
  prompt: string
  execution_mode?: 'full' | 'phase' | 'replay'
}

export interface WorkflowStartResponse {
  workflow_id: string
  task_id: string
  project_id: string
  current_phase: string
  status: string
  plan?: unknown
  architecture_decision?: unknown
  logs: unknown[]
}

export interface WorkflowPhaseRunResponse {
  workflow_id: string
  task_id: string
  current_phase: string
  status: string
  phases_state: Record<string, unknown>
  persisted_artifact_ids: string[]
  logs: unknown[]
}

// ─── Artifact + versions ─────────────────────────────────────────────────────

export interface ArtifactVersionResponse {
  id: string
  artifact_id: string
  version: number
  content: string
  validation_results: Record<string, unknown>
  generated_by?: string | null
  workflow_id?: string | null
  created_at: string
}

export interface ArtifactDetailResponse extends ArtifactResponse {
  versions: ArtifactVersionResponse[]
  approvals: ArtifactApprovalResponse[]
}
