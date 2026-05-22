import { apiClient } from './client'
import type {
  ApprovalAction,
  ArchitectureDecisionResponse,
  ArtifactApprovalResponse,
  ArtifactDetailResponse,
  ArtifactResponse,
  ArtifactVersionResponse,
  IdentityResponse,
  PhaseName,
  ProjectContextResponse,
  ProjectCreatePayload,
  ProjectDetailResponse,
  ProjectMemberResponse,
  ProjectResponse,
  ProjectRole,
  ProjectUpdatePayload,
  StartWorkflowPayload,
  WorkflowPhaseRunResponse,
  WorkflowResponse,
  WorkflowStartResponse,
} from '@/types/project'

export const projectsApi = {
  list: () =>
    apiClient.get<ProjectResponse[]>('/api/projects').then((r) => r.data),

  get: (id: string) =>
    apiClient.get<ProjectDetailResponse>(`/api/projects/${id}`).then((r) => r.data),

  create: (payload: ProjectCreatePayload) =>
    apiClient.post<ProjectResponse>('/api/projects', payload).then((r) => r.data),

  update: (id: string, payload: ProjectUpdatePayload) =>
    apiClient.patch<ProjectResponse>(`/api/projects/${id}`, payload).then((r) => r.data),

  retryBootstrap: (id: string) =>
    apiClient
      .post<ProjectResponse>(`/api/projects/${id}/bootstrap/retry`)
      .then((r) => r.data),

  listArtifacts: (id: string) =>
    apiClient
      .get<ArtifactResponse[]>(`/api/projects/${id}/artifacts`)
      .then((r) => r.data),

  listWorkflows: (id: string) =>
    apiClient
      .get<WorkflowResponse[]>(`/api/projects/${id}/workflows`)
      .then((r) => r.data),

  listMembers: (id: string) =>
    apiClient
      .get<ProjectMemberResponse[]>(`/api/projects/${id}/members`)
      .then((r) => r.data),

  // ─── Workflow execution ────────────────────────────────────────────────
  startWorkflow: (projectId: string, payload: StartWorkflowPayload) =>
    apiClient
      .post<WorkflowStartResponse>(`/api/projects/${projectId}/workflows`, payload)
      .then((r) => r.data),

  selectPlan: (projectId: string, workflowId: string, planId: string) =>
    apiClient
      .post<WorkflowPhaseRunResponse>(
        `/api/projects/${projectId}/workflows/${workflowId}/select-plan`,
        { plan_id: planId },
      )
      .then((r) => r.data),

  runPhase: (projectId: string, workflowId: string, phase: PhaseName) =>
    apiClient
      .post<WorkflowPhaseRunResponse>(
        `/api/projects/${projectId}/workflows/${workflowId}/phases/${phase}`,
      )
      .then((r) => r.data),

  getWorkflow: (projectId: string, workflowId: string) =>
    apiClient
      .get<WorkflowResponse>(`/api/projects/${projectId}/workflows/${workflowId}`)
      .then((r) => r.data),

  // ─── Artifact + versions ───────────────────────────────────────────────
  getArtifact: (projectId: string, artifactId: string) =>
    apiClient
      .get<ArtifactDetailResponse>(`/api/projects/${projectId}/artifacts/${artifactId}`)
      .then((r) => r.data),

  getArtifactVersion: (projectId: string, artifactId: string, version: number) =>
    apiClient
      .get<ArtifactVersionResponse>(
        `/api/projects/${projectId}/artifacts/${artifactId}/versions/${version}`,
      )
      .then((r) => r.data),

  // ─── Architecture decision ─────────────────────────────────────────────
  getArchitectureDecision: (projectId: string, workflowId: string) =>
    apiClient
      .get<ArchitectureDecisionResponse>(
        `/api/projects/${projectId}/workflows/${workflowId}/architecture-decision`,
      )
      .then((r) => r.data),

  // ─── Project context ───────────────────────────────────────────────────
  listContext: (projectId: string) =>
    apiClient
      .get<ProjectContextResponse[]>(`/api/projects/${projectId}/context`)
      .then((r) => r.data),

  // ─── Artifact approvals ────────────────────────────────────────────────
  listApprovals: (projectId: string, artifactId: string) =>
    apiClient
      .get<ArtifactApprovalResponse[]>(
        `/api/projects/${projectId}/artifacts/${artifactId}/approvals`,
      )
      .then((r) => r.data),

  createApproval: (
    projectId: string,
    artifactId: string,
    payload: { action: ApprovalAction; comment?: string },
  ) =>
    apiClient
      .post<ArtifactApprovalResponse>(
        `/api/projects/${projectId}/artifacts/${artifactId}/approvals`,
        payload,
      )
      .then((r) => r.data),

  // ─── Membership ─────────────────────────────────────────────────────────
  addMember: (projectId: string, payload: { user_id: string; role: ProjectRole }) =>
    apiClient
      .post<ProjectMemberResponse>(`/api/projects/${projectId}/members`, payload)
      .then((r) => r.data),

  updateMember: (projectId: string, memberId: string, role: ProjectRole) =>
    apiClient
      .patch<ProjectMemberResponse>(
        `/api/projects/${projectId}/members/${memberId}`,
        { role },
      )
      .then((r) => r.data),

  // ─── Identity ───────────────────────────────────────────────────────────
  getIdentity: () =>
    apiClient.get<IdentityResponse>('/api/projects/me/identity').then((r) => r.data),
}
