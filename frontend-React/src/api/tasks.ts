import { apiClient } from './client'
import type {
  TaskCreate,
  TaskResponse,
  PlanPreviewRequest,
  PlanPreviewResponse,
  GenerateArtifactsRequest,
  ReviewArtifactsRequest,
  ValidatePlanRequest,
  ValidatePlanResponse,
} from '@/types'

// Build a multipart/form-data body so we can attach the .env file
function buildFormData(
  fields: Record<string, string | string[] | undefined | null>,
  envFile?: File
): FormData {
  const fd = new FormData()
  for (const [key, value] of Object.entries(fields)) {
    if (value === undefined || value === null) continue
    if (Array.isArray(value)) {
      value.forEach((v) => fd.append(key, v))
    } else {
      fd.append(key, value)
    }
  }
  if (envFile) fd.append('env_file', envFile)
  return fd
}

export const tasksApi = {
  // List all tasks
  list: () =>
    apiClient.get<TaskResponse[]>('/tasks/').then((r) => r.data),

  // Get single task
  get: (id: string) =>
    apiClient.get<TaskResponse>(`/tasks/${id}`).then((r) => r.data),

  // Create task and run full workflow in one shot
  create: (payload: TaskCreate) =>
    apiClient.post<TaskResponse>('/tasks/', payload).then((r) => r.data),

  // Preview the generated plan — always sent as multipart so the .env file travels along
  planPreview: (payload: PlanPreviewRequest, envFile?: File) => {
    const fd = buildFormData(
      {
        prompt: payload.prompt,
        repo_url: payload.repo_url,
        repository_visibility: payload.repository_visibility,
        github_token: payload.github_token,
      },
      envFile
    )
    return apiClient
      .post<PlanPreviewResponse>('/tasks/plan-preview', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },

  // Generate artifacts after plan approval — carries the same .env file
  generate: (payload: GenerateArtifactsRequest, envFile?: File) => {
    const fd = buildFormData(
      {
        prompt: payload.prompt,
        repo_url: payload.repo_url,
        repository_visibility: payload.repository_visibility,
        github_token: payload.github_token,
        approved_artifacts: payload.approved_artifacts,
      },
      envFile
    )
    return apiClient
      .post<TaskResponse>('/tasks/generate', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },

  // Submit human review (edit artifacts + notes)
  review: (taskId: string, payload: ReviewArtifactsRequest) =>
    apiClient
      .post<TaskResponse>(`/tasks/${taskId}/review`, payload)
      .then((r) => r.data),

  // Validate (approve / reject / modify) a generated plan
  validatePlan: (payload: ValidatePlanRequest) =>
    apiClient
      .post<ValidatePlanResponse>('/tasks/validate-plan', payload)
      .then((r) => r.data),
}
