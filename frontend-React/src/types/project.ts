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
  name: string
  description?: string
  repository_url?: string
  architecture_type?: ArchitectureType
  application_profile?: string
  default_strategy_tier?: StrategyTier
}

export interface ProjectUpdatePayload {
  name?: string
  description?: string
  repository_url?: string
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
  architecture_type?: string | null
  application_profile?: string | null
  default_strategy_tier?: string | null
  current_status: ProjectStatus
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

export interface ArtifactResponse {
  id: string
  project_id: string
  workflow_id?: string | null
  artifact_type: string
  artifact_subtype: string
  content: string
  validation_status: ArtifactValidationStatus
  generated_by_agent?: string | null
  approved_by?: string | null
  version: number
  artifact_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
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
}
