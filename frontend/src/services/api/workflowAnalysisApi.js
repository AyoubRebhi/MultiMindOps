/* ============================================================================
   workflowAnalysisApi.js — WorkflowAnalysisService (project-scoped).

   Powers the Workflow Analysis Dashboard (/workflows/:projectId/analysis). The
   page makes exactly ONE call — getAnalysis(projectId) — and distributes the
   aggregated result to the five panels.

   REAL DATA, no mock. This is a read-only projection of the SAME persisted
   analysis that powers Project Details (/projects/:id):

       GET /api/projects/:projectId/workflow-analysis   ->  WorkflowAnalysis

   The backend builds that response from ProjectAnalysisService.build_payload —
   the identical source as GET /projects/:id/analysis — so both pages read the
   same persisted ProjectContext digests + security block. Nothing here (or in
   that endpoint) re-runs analysis, calls an LLM, or creates records.

   The snake_case→camelCase mapper (mapWorkflowPhaseAnalysis) is shared with the
   workflow-scoped surface (workflowApi.js), so both produce the same panel shape.

   @typedef {import('@/types/workflowAnalysis').WorkflowAnalysis} WorkflowAnalysis
   ========================================================================== */
import apiClient from './client';
import { mapWorkflowPhaseAnalysis } from './workflowApi';

export const workflowAnalysisApi = {
  /**
   * GET /api/projects/:projectId/workflow-analysis — the single aggregated
   * response, projected from the project's already-persisted analysis.
   * @param {string} projectId
   * @returns {Promise<WorkflowAnalysis>}
   */
  async getAnalysis(projectId) {
    const data = await apiClient.get(
      `/projects/${encodeURIComponent(projectId)}/workflow-analysis`
    );
    return mapWorkflowPhaseAnalysis(data);
  },

  /**
   * "Start"/"Rerun" on this read-only projection do NOT regenerate analysis —
   * the analysis already ran during project bootstrap. They simply re-read the
   * latest persisted projection so the view refreshes. (Real (re)analysis is
   * triggered from the project page, not here.)
   * @param {string} projectId
   */
  async startWorkflow(projectId) {
    return this.getAnalysis(projectId);
  },

  async rerunWorkflow(projectId) {
    return this.getAnalysis(projectId);
  },
};

export default workflowAnalysisApi;
