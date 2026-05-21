import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '@/api/projects'
import type {
  PhaseName,
  ProjectCreatePayload,
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
