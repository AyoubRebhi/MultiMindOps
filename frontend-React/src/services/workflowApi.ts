import { tasksApi } from '@/api/tasks'
import type {
  TaskResponse,
  PlanPreviewResponse,
  PlanPreviewRequest,
  GenerateArtifactsRequest,
  ValidatePlanRequest,
  ReviewArtifactsRequest,
  ArchitectureDecision,
} from '@/types'

// ── Step-by-step workflow API ─────────────────────────────────────────────────

export interface WorkflowPhaseResponse {
  task_id: string
  current_phase: string
  status: string
  artifacts: Record<string, string>
  terraform_outputs: Record<string, string>
  logs: unknown[]
  message: string
  // Populated for /architecture-decision and GET /workflow/{id}
  architecture_decision?: ArchitectureDecision
}

const BASE = (import.meta as unknown as { env: { VITE_API_BASE_URL?: string } }).env.VITE_API_BASE_URL ?? ''

// ── Docker Build Execution API ─────────────────────────────────────────────────

export interface DockerBuildStartResponse {
  status: string
  logs: unknown[]
  image_tag: string | null
  execution_phase: string
  ws_url: string
  task_id: string
}

export interface DockerBuildStatusResponse {
  status: string
  logs: unknown[]
  image_tag: string | null
  exit_code: number | null
  started_at: string | null
  finished_at: string | null
  duration_seconds: number | null
  retries: number
  build_number: number
  execution_phase: string
  current_phase: string
  task_id: string
  // Structured failure diagnostics
  failure_reason: string | null
  docker_command: string | null
  last_error_line: string | null
  failed_step: string | null
}

/** Start an async Docker build.  Returns immediately; connect WS for live logs. */
export async function startDockerBuild(taskId: string): Promise<DockerBuildStartResponse> {
  const res = await fetch(`${BASE}/api/execution/docker/build/${taskId}`, { method: 'POST' })
  if (!res.ok) {
    const d = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(d.detail ?? `Docker build start failed: ${res.status}`)
  }
  return res.json()
}

/** Poll persisted Docker build status (logs survive page refresh). */
export async function getDockerBuildStatus(taskId: string): Promise<DockerBuildStatusResponse> {
  const res = await fetch(`${BASE}/api/execution/docker/status/${taskId}`)
  if (!res.ok) throw new Error(`Failed to fetch build status: ${res.status}`)
  return res.json()
}

/** Compute the WebSocket URL for live execution log streaming. */
export function getWsExecutionUrl(taskId: string): string {
  const wsBase = BASE
    ? BASE.replace(/^http/, 'ws')
    : (typeof window !== 'undefined'
      ? `ws://${window.location.host}`
      : 'ws://localhost:8000')
  return `${wsBase}/ws/execution/${taskId}`
}

async function _workflowPost(path: string, body?: unknown): Promise<WorkflowPhaseResponse> {
  const res = await fetch(`${BASE}/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail.detail ?? `Request failed: ${res.status}`)
  }
  return res.json()
}

export async function workflowPlan(
  params: PlanPreviewRequest & { approved_artifacts?: string[] },
  envFile?: File | null,
): Promise<WorkflowPhaseResponse> {
  if (envFile) {
    const form = new FormData()
    form.append('prompt', params.prompt)
    if (params.repo_url) form.append('repo_url', params.repo_url)
    form.append('repository_visibility', params.repository_visibility ?? 'public')
    if (params.github_token) form.append('github_token', params.github_token)
    form.append('env_file', envFile)
    const res = await fetch(`${BASE}/api/workflow/plan`, { method: 'POST', body: form })
    if (!res.ok) {
      const d = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(d.detail ?? `Plan failed: ${res.status}`)
    }
    return res.json()
  }
  return _workflowPost('/workflow/plan', params)
}

/** Unified architecture decision phase — replaces /workflow/plan for new flow. */
export async function workflowArchitectureDecision(
  params: PlanPreviewRequest & { approved_artifacts?: string[] },
  envFile?: File | null,
): Promise<WorkflowPhaseResponse> {
  if (envFile) {
    const form = new FormData()
    form.append('prompt', params.prompt)
    if (params.repo_url) form.append('repo_url', params.repo_url)
    form.append('repository_visibility', params.repository_visibility ?? 'public')
    if (params.github_token) form.append('github_token', params.github_token)
    form.append('env_file', envFile)
    const res = await fetch(`${BASE}/api/workflow/architecture-decision`, { method: 'POST', body: form })
    if (!res.ok) {
      const d = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(d.detail ?? `Architecture decision failed: ${res.status}`)
    }
    return res.json()
  }
  return _workflowPost('/workflow/architecture-decision', params)
}

/** Confirm the user's plan selection — sets current_phase to planning_complete. */
export function workflowSelectPlan(
  taskId: string,
  planId: string,
): Promise<WorkflowPhaseResponse> {
  return _workflowPost(`/workflow/${taskId}/select-plan`, { plan_id: planId })
}

export function workflowRunDocker(taskId: string): Promise<WorkflowPhaseResponse> {
  return _workflowPost(`/workflow/${taskId}/run-docker`)
}

export function workflowRunTerraform(taskId: string): Promise<WorkflowPhaseResponse> {
  return _workflowPost(`/workflow/${taskId}/run-terraform`)
}

export function workflowRunKubernetes(taskId: string): Promise<WorkflowPhaseResponse> {
  return _workflowPost(`/workflow/${taskId}/run-kubernetes`)
}

export function workflowRunCicd(taskId: string): Promise<WorkflowPhaseResponse> {
  return _workflowPost(`/workflow/${taskId}/run-cicd`)
}

export async function workflowGetState(taskId: string): Promise<WorkflowPhaseResponse> {
  const res = await fetch(`${BASE}/api/workflow/${taskId}`)
  if (!res.ok) throw new Error(`Failed to fetch workflow state: ${res.status}`)
  return res.json()
}

// ── Plan generation ───────────────────────────────────────────────────────────

export function generatePlan(
  input: PlanPreviewRequest,
  envFile?: File,
): Promise<PlanPreviewResponse> {
  return tasksApi.planPreview(input, envFile)
}

// ── Human-validation approval (task already exists, backend unblocks) ─────────

export function approvePlanHumanValidation(
  payload: ValidatePlanRequest,
): ReturnType<typeof tasksApi.validatePlan> {
  return tasksApi.validatePlan(payload)
}

// ── Standard artifact generation (creates/continues task) ────────────────────

export function generateArtifacts(
  payload: GenerateArtifactsRequest,
  envFile?: File,
): Promise<TaskResponse> {
  return tasksApi.generate(payload, envFile)
}

// ── Polling ───────────────────────────────────────────────────────────────────

export function pollTask(taskId: string): Promise<TaskResponse> {
  return tasksApi.get(taskId)
}

// ── Review (submit edited artifacts) ─────────────────────────────────────────

export function submitReview(
  taskId: string,
  reviewedArtifacts: Record<string, string>,
  notes?: string,
): Promise<TaskResponse> {
  const payload: ReviewArtifactsRequest = {
    reviewed_artifacts: reviewedArtifacts,
    review_notes: notes,
  }
  return tasksApi.review(taskId, payload)
}

// ── Artifact key → display filename ──────────────────────────────────────────

export const DISPLAY_NAME: Record<string, string> = {
  dockerfile:              'Dockerfile',
  dockerignore:            '.dockerignore',
  docker_compose:          'docker-compose.yml',
  env_example:             '.env.example',
  terraform_providers:     'providers.tf',
  terraform_backend:       'backend.tf',
  terraform_vpc:           'vpc.tf',
  terraform_compute:       'compute.tf',
  terraform_eks:           'eks.tf',
  terraform_variables:     'variables.tf',
  terraform_outputs:       'outputs.tf',
  terraform_main:          'main.tf',
  terraform_iam:           'iam.tf',
  terraform_sg:            'security_groups.tf',
  terraform_alb:           'alb.tf',
  kubernetes_deployment:   'deployment.yaml',
  kubernetes_service:      'service.yaml',
  kubernetes_ingress:      'ingress.yaml',
  kubernetes_configmap:    'configmap.yaml',
  kubernetes_hpa:          'hpa.yaml',
  kubernetes_namespace:    'namespace.yaml',
  github_actions_workflow: '.github/workflows/ci-cd.yml',
  cicd_workflow:           '.github/workflows/ci-cd.yml',
}

export function displayName(key: string): string {
  return DISPLAY_NAME[key] ?? key
}

export function artifactLanguage(key: string): string {
  if (key === 'dockerfile' || key === 'dockerignore') return 'dockerfile'
  if (key.startsWith('docker_')) return 'yaml'
  if (key.startsWith('terraform_')) return 'hcl'
  if (key.startsWith('kubernetes_')) return 'yaml'
  if (key.includes('workflow') || key.includes('cicd') || key.includes('github_actions')) return 'yaml'
  return 'text'
}

// ── Artifact extraction helpers ───────────────────────────────────────────────

const DOCKER_KEYS = new Set(['dockerfile', 'dockerignore', 'docker_compose', 'env_example'])

export function getInfraArtifacts(task: TaskResponse): Record<string, string> {
  const fromInfra = (task.infra?.artifacts ?? {}) as Record<string, string>
  const fromResultInfra = ((task.result?.infrastructure as { artifacts?: Record<string, string> })?.artifacts ?? {})
  const legacy = (task.result?.artifacts ?? {}) as Record<string, string>

  const combined: Record<string, string> = { ...legacy, ...fromResultInfra, ...fromInfra }

  return Object.fromEntries(
    Object.entries(combined).filter(([k]) =>
      DOCKER_KEYS.has(k) || k.startsWith('docker_'),
    ),
  )
}

export function getTerraformArtifacts(task: TaskResponse): Record<string, string> {
  // Priority order (highest first): task.infra.artifacts → result.infrastructure.artifacts → result.artifacts (legacy)
  const fromInfra      = (task.infra?.artifacts ?? {}) as Record<string, string>
  const fromResultInfra = ((task.result?.infrastructure as { artifacts?: Record<string, string> })?.artifacts ?? {})
  const legacy          = (task.result?.artifacts ?? {}) as Record<string, string>
  const combined: Record<string, string> = { ...legacy, ...fromResultInfra, ...fromInfra }

  return Object.fromEntries(
    Object.entries(combined).filter(([k]) => k.startsWith('terraform_')),
  )
}

export function getKubernetesArtifacts(task: TaskResponse): Record<string, string> {
  // Priority order (highest first): task.infra.artifacts → result.infrastructure.artifacts → result.artifacts (legacy)
  const fromInfra      = (task.infra?.artifacts ?? {}) as Record<string, string>
  const fromResultInfra = ((task.result?.infrastructure as { artifacts?: Record<string, string> })?.artifacts ?? {})
  const legacy          = (task.result?.artifacts ?? {}) as Record<string, string>
  const combined: Record<string, string> = { ...legacy, ...fromResultInfra, ...fromInfra }

  return Object.fromEntries(
    Object.entries(combined).filter(([k]) => k.startsWith('kubernetes_')),
  )
}

export function getCicdArtifacts(task: TaskResponse): Record<string, string> {
  // task.cicd may be a nested object with `.artifacts` key (from the backend's CICDAgent output)
  const rawCicd = (task.cicd ?? {}) as Record<string, unknown>
  const fromCicdArtifacts = (rawCicd['artifacts'] ?? rawCicd) as Record<string, string>

  const rawResultCicd = ((task.result?.cicd ?? {}) as Record<string, unknown>)
  const fromResultCicdArtifacts = (rawResultCicd['artifacts'] ?? rawResultCicd) as Record<string, string>

  const fromResultFlat = Object.fromEntries(
    Object.entries((task.result?.artifacts ?? {}) as Record<string, string>).filter(([k]) =>
      k.includes('workflow') || k.includes('cicd') || k.includes('github_actions'),
    ),
  )
  return { ...fromResultFlat, ...fromResultCicdArtifacts, ...fromCicdArtifacts }
}

export function getSummary(task: TaskResponse): string {
  return (task.result?.summary as string) ?? ''
}

// ── Download helper ───────────────────────────────────────────────────────────

export function downloadFile(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/plain' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function downloadAllArtifacts(task: TaskResponse, editedArtifacts: Record<string, string>) {
  const sections: string[] = []

  const allArtifacts: Record<string, string> = {
    ...getInfraArtifacts(task),
    ...getTerraformArtifacts(task),
    ...getKubernetesArtifacts(task),
    ...getCicdArtifacts(task),
  }

  for (const [key, original] of Object.entries(allArtifacts)) {
    const content = editedArtifacts[key] ?? original
    const name    = displayName(key)
    sections.push(`${'='.repeat(60)}\n# ${name}\n${'='.repeat(60)}\n${content}\n`)
  }

  if (sections.length) {
    downloadFile('devsecops-artifacts.txt', sections.join('\n'))
  }
}
