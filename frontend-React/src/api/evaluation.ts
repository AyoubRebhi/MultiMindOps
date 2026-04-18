import { apiClient } from './client'

// ─── Artifact judge ───────────────────────────────────────────────────────────

export type ArtifactType =
  | 'dockerfile'
  | 'docker-compose'
  | 'python'
  | 'yaml'
  | 'terraform'
  | 'typescript'
  | 'documentation'

export interface JudgeRequest {
  artifact_type: ArtifactType | string
  artifact_content: string
  context?: Record<string, string>
}

export interface MetricDetail {
  score: number
  feedback: string
}

export interface JudgeResponse {
  artifact_type: string
  global_score: number
  metrics: {
    correction: MetricDetail
    performance: MetricDetail
    security: MetricDetail
    maintainability: MetricDetail
  }
  recommendations: string[]
  detailed_report: string
}

export async function judgeArtifact(req: JudgeRequest): Promise<JudgeResponse> {
  const { data } = await apiClient.post<JudgeResponse>('/evaluation/judge', req)
  return data
}

// ─── Plan judge ───────────────────────────────────────────────────────────────

export interface PlanJudgeRequest {
  plan_dict: Record<string, unknown>
  original_prompt: string
  context?: Record<string, unknown>
}

export interface PlanMetricDetail {
  score: number
  feedback: string
}

export interface PlanJudgeResponse {
  artifact_type: string
  global_score: number
  metrics: {
    completeness: PlanMetricDetail
    clarity: PlanMetricDetail
    agent_readiness: PlanMetricDetail
    security_fit: PlanMetricDetail
  }
  recommendations: string[]
  detailed_report: string
}

export async function judgePlan(req: PlanJudgeRequest): Promise<PlanJudgeResponse> {
  const { data } = await apiClient.post<PlanJudgeResponse>('/evaluation/plan', req)
  return data
}
