/* ============================================================================
   cicdIntentApi.js — the CI/CD Request Analysis + Intent Extraction agents.
   Returns the request analysis (Section 1) and the structured intent the agent
   extracted from the user request (Section 2). MOCK ONLY.
   ========================================================================== */
import {
  mockRequestAnalysis,
  mockIntentExtraction,
} from '@/services/mock/mockIntentExtraction';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const cicdIntentApi = {
  /** GET /projects/:projectId/cicd/request-analysis */
  async getRequestAnalysis() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/cicd/request-analysis`);
    return mockResponse(mockRequestAnalysis);
  },

  /** GET /projects/:projectId/cicd/intent */
  async getIntent() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/cicd/intent`);
    return mockResponse(mockIntentExtraction);
  },
};

export default cicdIntentApi;
