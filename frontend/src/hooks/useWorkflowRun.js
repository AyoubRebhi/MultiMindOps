import { useAsync } from './useAsync';
import { workflowApi } from '@/services/api/workflowApi';

/**
 * useWorkflowRun — fetch one workflow summary (GET /workflows/:id) so a click
 * on a workflow can RESUME from its saved phase. Returns status + current_phase
 * the resume router reads to pick the right phase view. Does NOT start, rerun,
 * or mutate the workflow.
 *
 * @param {string} workflowId
 */
export function useWorkflowRun(workflowId) {
  return useAsync(
    () => (workflowId ? workflowApi.get(workflowId) : Promise.resolve(null)),
    [workflowId],
    { immediate: !!workflowId }
  );
}

/**
 * useWorkflowPhaseAnalysis — fetch the single aggregated Analysis-phase payload
 * (GET /workflows/:id/analysis). One request, five sections. Read-only: the
 * analysis already ran during project bootstrap, so there is no polling or
 * mutation here.
 *
 * @param {string} workflowId
 */
export function useWorkflowPhaseAnalysis(workflowId) {
  return useAsync(
    () => (workflowId ? workflowApi.getAnalysis(workflowId) : Promise.resolve(null)),
    [workflowId],
    { immediate: !!workflowId }
  );
}

/**
 * useArchitectureDecision — fetch the AI-generated architecture plans for the
 * Architecture Planning phase (GET project-scoped .../architecture-decision).
 * Both ids are required because the read + selection endpoints are project-
 * scoped. Returns { data, loading, error, refetch } — refetch re-reads the
 * authoritative selection after a plan is persisted.
 *
 * @param {string} projectId
 * @param {string} workflowId
 */
export function useArchitectureDecision(projectId, workflowId) {
  const ready = !!projectId && !!workflowId;
  return useAsync(
    () =>
      ready
        ? workflowApi.getArchitectureDecision(projectId, workflowId)
        : Promise.resolve(null),
    [projectId, workflowId],
    { immediate: ready }
  );
}

/**
 * useDockerPhase — fetch the aggregated Docker-Generation payload for the Docker
 * phase (GET project-scoped .../docker). Both ids are required (the read +
 * run endpoints are project-scoped). Returns { data, loading, error, refetch }.
 * Read-only: generation/correction already ran on the backend, so the surface
 * polls via `refetch` only after it triggers the DOCKER phase itself.
 *
 * @param {string} projectId
 * @param {string} workflowId
 */
export function useDockerPhase(projectId, workflowId) {
  const ready = !!projectId && !!workflowId;
  return useAsync(
    () =>
      ready
        ? workflowApi.getDockerPhase(projectId, workflowId)
        : Promise.resolve(null),
    [projectId, workflowId],
    { immediate: ready }
  );
}

export default useWorkflowRun;
