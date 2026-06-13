/* ============================================================================
   historyApi.js — previous workflow executions for the Infrastructure
   Dashboard (Section 6), rendered by <WorkflowHistoryPanel />. MOCK ONLY.
   ========================================================================== */
import { mockWorkflowHistory } from '@/services/mock/mockWorkflowHistory';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const historyApi = {
  /** GET /projects/:projectId/workflow/history */
  async listExecutions() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/workflow/history`);
    return mockResponse(mockWorkflowHistory);
  },
};

export default historyApi;
