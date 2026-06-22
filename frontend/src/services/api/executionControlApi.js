/* ============================================================================
   executionControlApi.js — Phase 3A: Stop (cancel) + Replay for long-running
   workflow phases (Docker build, Terraform validate/plan).

   Both endpoints ALREADY exist on the backend (see Phase 0 audit):

     Cancel a running job (durable execution_jobs row)
       POST /projects/:pid/jobs/:jobId/cancel
         → { id, status, message }
         status is the state AT THE MOMENT OF THE REQUEST:
           "cancelled" (a pending job, or a terminal job, settled immediately) or
           "running"   (a running job was flagged; the worker stops it shortly —
                        the WS then emits {type:"complete", status:"cancelled"}).

     Replay a workflow deterministically from DB artifacts ONLY (no LLM, no
     regeneration) — re-enqueues the same durable terraform/docker jobs.
       POST /projects/:pid/workflows/:wid/replay
         → { ...summary: re-enqueued job ids + stream keys, skipped steps }

   These are the ONLY control-plane calls the Stop/Replay buttons make; the live
   log experience continues to flow over the existing WebSockets.
   ========================================================================== */
import apiClient from './client';

export const executionControlApi = {
  /**
   * POST a cancellation request for a durable job. Idempotent: a terminal job
   * is returned unchanged. Returns { id, status, message }.
   *
   * @param {string} projectId
   * @param {string} jobId
   */
  async cancelJob(projectId, jobId) {
    return apiClient.post(
      `/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(
        jobId
      )}/cancel`,
      {}
    );
  },

  /**
   * POST a deterministic replay of a workflow's executable steps from DB
   * artifacts. Re-enqueues the same terraform/docker jobs the normal phases
   * would; performs NO LLM calls and NO regeneration. Returns the replay summary.
   *
   * @param {string} projectId
   * @param {string} workflowId
   */
  async replayWorkflow(projectId, workflowId) {
    return apiClient.post(
      `/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(
        workflowId
      )}/replay`,
      {}
    );
  },
};

export default executionControlApi;
