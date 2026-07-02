import { useEffect } from 'react';
import { useAsync } from './useAsync';
import {
  workflowApi,
  mapTerraformArtifacts,
  mapTerraformValidationReport,
  mapTerraformPlanArtifact,
  mapInfrastructureSummary,
} from '@/services/api/workflowApi';

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
 * useWorkflowPhases — fetch the authoritative `phases_state` (with per-phase
 * revision/invalidation metadata) plus the revision history in ONE shot. Powers
 * the workflow phase navigator + the Regenerate action + the dependency warning.
 * Both ids are required (the project-scoped row carries phases_state; the resume
 * summary from GET /workflows/:id does not). The revision history degrades to []
 * if its fetch fails so a missing-history error never blanks the navigator.
 * Returns { data: { phasesState, currentPhase, status, revisions }, ..., refetch }.
 *
 * @param {string} projectId
 * @param {string} workflowId
 */
export function useWorkflowPhases(projectId, workflowId) {
  const ready = !!projectId && !!workflowId;
  return useAsync(
    async () => {
      if (!ready) return null;
      const wf = await workflowApi.getProjectWorkflow(projectId, workflowId);
      let revisions = [];
      try {
        const history = await workflowApi.getRevisionHistory(projectId, workflowId);
        revisions = history?.revisions || [];
      } catch {
        revisions = [];
      }
      return {
        phasesState: wf?.phasesState || {},
        currentPhase: wf?.currentPhase || null,
        status: wf?.status || null,
        revisions,
      };
    },
    [projectId, workflowId],
    { immediate: ready }
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

/**
 * useGithubActionsPhase — fetch the aggregated GitHub Actions Generation payload
 * (GET project-scoped .../github-actions). Both ids are required (the read + run
 * endpoints are project-scoped). Returns { data, loading, error, refetch }.
 * Read-only: generation already ran on the backend, so the surface polls via
 * `refetch` only after it triggers the GITHUB_ACTIONS_GENERATION phase itself.
 *
 * @param {string} projectId
 * @param {string} workflowId
 */
export function useGithubActionsPhase(projectId, workflowId) {
  const ready = !!projectId && !!workflowId;
  return useAsync(
    () =>
      ready
        ? workflowApi.getGithubActionsPhase(projectId, workflowId)
        : Promise.resolve(null),
    [projectId, workflowId],
    { immediate: ready }
  );
}

/**
 * useRepositoryInstallationPhase — fetch the aggregated installation payload (GET
 * project-scoped .../repository-installation). Both ids are required (the read +
 * run endpoints are project-scoped). Returns { data, loading, error, refetch }.
 * Read-only: the install already ran on the backend, so the surface polls via
 * `refetch` only after it triggers the REPOSITORY_INSTALLATION phase itself.
 *
 * @param {string} projectId
 * @param {string} workflowId
 */
export function useRepositoryInstallationPhase(projectId, workflowId) {
  const ready = !!projectId && !!workflowId;
  return useAsync(
    () =>
      ready
        ? workflowApi.getRepositoryInstallationPhase(projectId, workflowId)
        : Promise.resolve(null),
    [projectId, workflowId],
    { immediate: ready }
  );
}

/**
 * useWorkflowMonitoring — fetch the live GitHub Actions monitoring snapshot (GET
 * project-scoped .../monitoring) for the two installed pipelines, and POLL it on
 * an interval (default 30s) so the surface reflects run progress without a
 * WebSocket. Read-only: the backend only observes — it never triggers, reruns,
 * or cancels a workflow. `refetch` powers the manual refresh button.
 *
 * Polling auto-pauses once BOTH pipelines have reached a terminal conclusion
 * (nothing left to watch); a manual refresh still works. Returns
 * { data, loading, error, refetch }.
 *
 * @param {string} projectId
 * @param {string} workflowId
 * @param {number} pollMs   poll interval in ms (default 30000)
 */
export function useWorkflowMonitoring(projectId, workflowId, pollMs = 30000) {
  const ready = !!projectId && !!workflowId;
  const state = useAsync(
    () =>
      ready
        ? workflowApi.getWorkflowMonitoring(projectId, workflowId)
        : Promise.resolve(null),
    [projectId, workflowId],
    { immediate: ready }
  );

  const { data, refetch } = state;
  // A run is "live" while it exists and has not concluded. We keep polling while
  // EITHER pipeline is live (or while we have no data yet, e.g. first/degraded
  // load), and stop once both are terminal to avoid pointless requests.
  const isLive = (p) => p && p.found && !p.conclusion;
  const keepPolling =
    ready && (!data || isLive(data.infrastructure) || isLive(data.delivery));

  useEffect(() => {
    if (!keepPolling || !pollMs) return undefined;
    const id = setInterval(() => {
      refetch();
    }, pollMs);
    return () => clearInterval(id);
  }, [keepPolling, pollMs, refetch]);

  return state;
}

/**
 * useDestroyPhase — fetch the Infrastructure Destroy payload (GET .../destroy)
 * and POLL it while the destroy is in flight, so the surface reflects the live
 * destroy.yml run (observed exactly like bootstrap.yml) without a WebSocket.
 * Read-only: the backend never runs Terraform; `refetch` powers the manual
 * refresh and is called after the surface triggers the destroy itself.
 *
 * Polling auto-stops once the run reaches a terminal state (succeeded/failed) or
 * was never triggered. Returns { data, loading, error, refetch }.
 *
 * @param {string} projectId
 * @param {string} workflowId
 * @param {number} pollMs   poll interval in ms (default 15000)
 */
export function useDestroyPhase(projectId, workflowId, pollMs = 15000) {
  const ready = !!projectId && !!workflowId;
  const state = useAsync(
    () =>
      ready
        ? workflowApi.getDestroyPhase(projectId, workflowId)
        : Promise.resolve(null),
    [projectId, workflowId],
    { immediate: ready }
  );

  const { data, refetch } = state;
  // Keep polling while a destroy is requested/running (it advances on the
  // backend as the GitHub Actions run progresses); stop once terminal.
  const keepPolling = ready && (data?.requested || data?.running);

  useEffect(() => {
    if (!keepPolling || !pollMs) return undefined;
    const id = setInterval(() => {
      refetch();
    }, pollMs);
    return () => clearInterval(id);
  }, [keepPolling, pollMs, refetch]);

  return state;
}

/**
 * useRecoveryPhase — fetch the read-only Infrastructure Recovery diagnosis (GET
 * .../recovery) for a failed bootstrap. The backend is purely diagnostic (it
 * never runs Terraform / touches AWS); `refetch` powers the manual refresh.
 *
 * Polls lightly while the bootstrap run is still in flight (not yet failed and
 * no report) so the surface flips to "Recovery available" as soon as a failure
 * is observed; stops once a report exists or there is nothing to watch.
 *
 * @param {string} projectId
 * @param {string} workflowId
 * @param {number} pollMs   poll interval in ms (default 20000)
 */
export function useRecoveryPhase(projectId, workflowId, pollMs = 20000) {
  const ready = !!projectId && !!workflowId;
  const state = useAsync(
    () =>
      ready
        ? workflowApi.getRecoveryPhase(projectId, workflowId)
        : Promise.resolve(null),
    [projectId, workflowId],
    { immediate: ready }
  );

  const { data, refetch } = state;
  // Keep polling only while we have data, the run is being observed, and no
  // failure has been diagnosed yet (so a fresh failure surfaces automatically).
  const keepPolling =
    ready && !!data && data.monitoringAvailable && !data.recoveryAvailable;

  useEffect(() => {
    if (!keepPolling || !pollMs) return undefined;
    const id = setInterval(() => {
      refetch();
    }, pollMs);
    return () => clearInterval(id);
  }, [keepPolling, pollMs, refetch]);

  return state;
}

/**
 * useLifecyclePhase — fetch the Infrastructure Lifecycle dashboard (GET
 * .../lifecycle) and POLL it while a run is in flight, so status, history and
 * action availability stay live without a WebSocket. Read-only fetch; `refetch`
 * powers the manual Refresh button and is called after retry/destroy actions.
 *
 * @param {string} projectId
 * @param {string} workflowId
 * @param {number} pollMs   poll interval in ms (default 20000)
 */
export function useLifecyclePhase(projectId, workflowId, pollMs = 20000) {
  const ready = !!projectId && !!workflowId;
  const state = useAsync(
    () =>
      ready
        ? workflowApi.getLifecyclePhase(projectId, workflowId)
        : Promise.resolve(null),
    [projectId, workflowId],
    { immediate: ready }
  );

  const { data, refetch } = state;
  // Keep polling while any observed pipeline run is still in flight.
  const isLive = (r) => r && r.found && !r.conclusion;
  const keepPolling =
    ready && !!data &&
    (isLive(data.bootstrapRun) || isLive(data.deployRun) || isLive(data.destroyRun));

  useEffect(() => {
    if (!keepPolling || !pollMs) return undefined;
    const id = setInterval(() => {
      refetch();
    }, pollMs);
    return () => clearInterval(id);
  }, [keepPolling, pollMs, refetch]);

  return state;
}

/**
 * useTerraformPhase — fetch everything the Terraform surface needs (Generation
 * AND Validation) in ONE shot, from existing endpoints: the workflow's
 * authoritative `phases_state` (GET project-scoped workflow) and the project
 * artifacts (GET project artifacts, read once → split into the generated `.tf`
 * files and the `validation_report`). Phase status is read EXCLUSIVELY from
 * phases_state; artifacts/report are for display only. Returns
 * { data: { phasesState, currentPhase, status, artifacts, validationReport,
 * planArtifact, infrastructureSummary }, loading, error, refetch } — `refetch`
 * re-reads both after the surface triggers TERRAFORM_GENERATION /
 * TERRAFORM_VALIDATION / TERRAFORM_PLAN (or when a validation/plan stream ends).
 * `infrastructureSummary` here is the artifact-derived FALLBACK; the surface
 * prefers the copy embedded in phases_state.TERRAFORM_PLAN.
 *
 * @param {string} projectId
 * @param {string} workflowId
 */
export function useTerraformPhase(projectId, workflowId) {
  const ready = !!projectId && !!workflowId;
  return useAsync(
    async () => {
      if (!ready) return null;
      const [wf, rawArtifacts] = await Promise.all([
        workflowApi.getProjectWorkflow(projectId, workflowId),
        workflowApi.getProjectArtifacts(projectId),
      ]);
      return {
        phasesState: wf?.phasesState || {},
        currentPhase: wf?.currentPhase || null,
        status: wf?.status || null,
        artifacts: mapTerraformArtifacts(rawArtifacts),
        validationReport: mapTerraformValidationReport(rawArtifacts),
        planArtifact: mapTerraformPlanArtifact(rawArtifacts),
        infrastructureSummary: mapInfrastructureSummary(rawArtifacts),
      };
    },
    [projectId, workflowId],
    { immediate: ready }
  );
}

export default useWorkflowRun;
