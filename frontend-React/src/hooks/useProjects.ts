import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '@/api/projects'
import type {
  ApprovalAction,
  PhaseName,
  ProjectCreatePayload,
  ProjectRole,
  ProjectUpdatePayload,
  StartWorkflowPayload,
} from '@/types/project'

export const PROJECTS_KEY = ['projects']

export function useProjectList() {
  return useQuery({
    queryKey: PROJECTS_KEY,
    queryFn: projectsApi.list,
    refetchInterval: 15_000,
  })
}

export function useProject(id: string) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, id],
    queryFn: () => projectsApi.get(id),
    enabled: Boolean(id),
    // Poll while the bootstrap is in-flight so the ProjectDetail UI advances
    // through analyzing → context_building → ready without a manual refresh.
    refetchInterval: (query) => {
      const status = query.state.data?.bootstrap_status
      if (status === 'pending' || status === 'analyzing' || status === 'context_building') {
        return 3_000
      }
      return false
    },
  })
}

export function useRetryBootstrap(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => projectsApi.retryBootstrap(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [...PROJECTS_KEY, id] })
      qc.invalidateQueries({ queryKey: [...PROJECTS_KEY, id, 'workflows'] })
      qc.invalidateQueries({ queryKey: [...PROJECTS_KEY, id, 'context'] })
    },
  })
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: ProjectCreatePayload) => projectsApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: PROJECTS_KEY }),
  })
}

export function useUpdateProject(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: ProjectUpdatePayload) => projectsApi.update(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: PROJECTS_KEY })
      qc.invalidateQueries({ queryKey: [...PROJECTS_KEY, id] })
    },
  })
}

export function useProjectArtifacts(id: string) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, id, 'artifacts'],
    queryFn: () => projectsApi.listArtifacts(id),
    enabled: Boolean(id),
  })
}

export function useProjectWorkflows(id: string) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, id, 'workflows'],
    queryFn: () => projectsApi.listWorkflows(id),
    enabled: Boolean(id),
  })
}

export function useProjectMembers(id: string) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, id, 'members'],
    queryFn: () => projectsApi.listMembers(id),
    enabled: Boolean(id),
  })
}

// ─── Workflow execution ──────────────────────────────────────────────────────

function invalidateProject(qc: ReturnType<typeof useQueryClient>, projectId: string) {
  qc.invalidateQueries({ queryKey: [...PROJECTS_KEY, projectId] })
  qc.invalidateQueries({ queryKey: [...PROJECTS_KEY, projectId, 'workflows'] })
  qc.invalidateQueries({ queryKey: [...PROJECTS_KEY, projectId, 'artifacts'] })
}

export function useStartWorkflow(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: StartWorkflowPayload) =>
      projectsApi.startWorkflow(projectId, payload),
    onSuccess: () => invalidateProject(qc, projectId),
  })
}

export function useRunPhase(projectId: string, workflowId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (phase: PhaseName) => projectsApi.runPhase(projectId, workflowId, phase),
    onSuccess: () => invalidateProject(qc, projectId),
  })
}

export function useSelectPlan(projectId: string, workflowId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (planId: string) => projectsApi.selectPlan(projectId, workflowId, planId),
    onSuccess: () => invalidateProject(qc, projectId),
  })
}

export function useArtifactDetail(projectId: string, artifactId: string | null) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, projectId, 'artifact', artifactId],
    queryFn: () => projectsApi.getArtifact(projectId, artifactId as string),
    enabled: Boolean(projectId && artifactId),
  })
}

// ─── Architecture decision ──────────────────────────────────────────────────

export function useArchitectureDecision(projectId: string, workflowId: string | null) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, projectId, 'workflow', workflowId, 'architecture-decision'],
    queryFn: () =>
      projectsApi.getArchitectureDecision(projectId, workflowId as string),
    enabled: Boolean(projectId && workflowId),
    // 404 = no decision yet; don't keep retrying.
    retry: (failureCount, error) => {
      const status = (error as { response?: { status?: number } })?.response?.status
      if (status === 404) return false
      return failureCount < 2
    },
  })
}

// ─── Project context ────────────────────────────────────────────────────────

export function useProjectContext(projectId: string) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, projectId, 'context'],
    queryFn: () => projectsApi.listContext(projectId),
    enabled: Boolean(projectId),
    refetchInterval: 30_000,
  })
}

// ─── Artifact approvals ─────────────────────────────────────────────────────

export function useCreateApproval(projectId: string, artifactId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { action: ApprovalAction; comment?: string }) =>
      projectsApi.createApproval(projectId, artifactId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [...PROJECTS_KEY, projectId, 'artifact', artifactId] })
      qc.invalidateQueries({ queryKey: [...PROJECTS_KEY, projectId, 'artifacts'] })
    },
  })
}

// ─── Membership mutations ───────────────────────────────────────────────────

export function useAddProjectMember(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { user_id: string; role: ProjectRole }) =>
      projectsApi.addMember(projectId, payload),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: [...PROJECTS_KEY, projectId, 'members'] }),
  })
}

export function useUpdateProjectMember(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ memberId, role }: { memberId: string; role: ProjectRole }) =>
      projectsApi.updateMember(projectId, memberId, role),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: [...PROJECTS_KEY, projectId, 'members'] }),
  })
}

// ─── Identity / role ────────────────────────────────────────────────────────

export function useIdentity() {
  return useQuery({
    queryKey: ['identity'],
    queryFn: projectsApi.getIdentity,
    staleTime: 60_000,
  })
}

/** Resolves the caller's role on a given project. Returns null while loading. */
export function useProjectRole(projectId: string): ProjectRole | null {
  const { data } = useIdentity()
  if (!data) return null
  return (
    data.memberships.find((m) => m.project_id === projectId)?.role ?? null
  )
}
