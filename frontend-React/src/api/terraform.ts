import { apiClient } from './client'

export type TerraformArchitecture = 'monolith' | 'microservices' | 'serverless'
export type TerraformTier = 'balanced'

export interface TerraformGenerateRequest {
  architecture: TerraformArchitecture
  tier?: TerraformTier
  project_name?: string
}

export interface TerraformArtifact {
  id: string
  files: Record<string, string>
  metadata: Record<string, unknown>
}

export interface TerraformValidationLog {
  ok: boolean
  stdout: string
  stderr: string
}

export interface TerraformValidationResult {
  id: string
  valid: boolean
  init: TerraformValidationLog
  validate: TerraformValidationLog
  duration_ms: number
}

export const terraformApi = {
  generate: (payload: TerraformGenerateRequest) =>
    apiClient
      .post<TerraformArtifact>('/terraform/generate', {
        architecture: payload.architecture,
        tier: payload.tier ?? 'balanced',
        project_name: payload.project_name,
      })
      .then((r) => r.data),

  validate: (artifactId: string) =>
    apiClient
      .post<TerraformValidationResult>(`/terraform/validate/${artifactId}`)
      .then((r) => r.data),

  get: (artifactId: string) =>
    apiClient
      .get<TerraformArtifact>(`/terraform/artifacts/${artifactId}`)
      .then((r) => r.data),
}
