import { tasksApi } from '@/api/tasks'
import type {
  TaskResponse,
  PlanPreviewResponse,
  PlanPreviewRequest,
  GenerateArtifactsRequest,
  ValidatePlanRequest,
  ReviewArtifactsRequest,
} from '@/types'

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
  const fromInfra = (task.infra?.artifacts ?? {}) as Record<string, string>
  const legacy = (task.result?.artifacts ?? {}) as Record<string, string>
  const combined: Record<string, string> = { ...legacy, ...fromInfra }

  return Object.fromEntries(
    Object.entries(combined).filter(([k]) => k.startsWith('terraform_')),
  )
}

export function getKubernetesArtifacts(task: TaskResponse): Record<string, string> {
  const fromInfra = (task.infra?.artifacts ?? {}) as Record<string, string>
  const legacy = (task.result?.artifacts ?? {}) as Record<string, string>
  const combined: Record<string, string> = { ...legacy, ...fromInfra }

  return Object.fromEntries(
    Object.entries(combined).filter(([k]) => k.startsWith('kubernetes_')),
  )
}

export function getCicdArtifacts(task: TaskResponse): Record<string, string> {
  const direct = (task.cicd ?? {}) as Record<string, string>
  const fromResult = ((task.result?.cicd as Record<string, string>) ?? {})
  const fromArtifacts = Object.fromEntries(
    Object.entries((task.result?.artifacts ?? {}) as Record<string, string>).filter(([k]) =>
      k.includes('workflow') || k.includes('cicd') || k.includes('github_actions'),
    ),
  )
  return { ...direct, ...fromResult, ...fromArtifacts }
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
