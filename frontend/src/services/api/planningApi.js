/* ============================================================================
   planningApi.js — Planning Agent result + the candidate architecture plans
   shown on the Planning phase page. MOCK ONLY.
   ========================================================================== */
import { mockPlanningResult, mockPlans } from '@/services/mock/mockPlans';
import { mockResponse, mockError } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const planningApi = {
  /** GET /projects/:projectId/planning — the planning agent's analysis. */
  async getPlanning(projectId) {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/planning`);
    return mockResponse({ ...mockPlanningResult, projectId: projectId || mockPlanningResult.projectId });
  },

  /** GET /projects/:projectId/plans — the 3 candidate plans. */
  async listPlans() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/plans`);
    return mockResponse(mockPlans);
  },

  /** POST /projects/:projectId/plans/:planId/select — record the chosen plan. */
  async selectPlan(planId) {
    // if (!USE_MOCK) return apiClient.post(`/plans/${planId}/select`);
    const plan = mockPlans.find((p) => p.id === planId);
    if (!plan) return mockError(`Plan "${planId}" not found`, 404);
    return mockResponse({ selectedPlanId: planId, plan }, { minMs: 250, maxMs: 500 });
  },
};

export default planningApi;
