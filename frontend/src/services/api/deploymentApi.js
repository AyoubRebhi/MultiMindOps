/* ============================================================================
   deploymentApi.js — the deployment target (Section 6 of the Execution Center)
   and the final deployment overview (Section 1 of the Infrastructure
   Dashboard). MOCK ONLY — nothing is deployed.
   ========================================================================== */
import { mockDeploymentTarget } from '@/services/mock/mockDeploymentTarget';
import { mockDeploymentOverview } from '@/services/mock/mockDeploymentResults';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const deploymentApi = {
  /** GET /projects/:projectId/deployment/target */
  async getTarget() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/deployment/target`);
    return mockResponse(mockDeploymentTarget);
  },

  /** GET /projects/:projectId/deployment/overview */
  async getOverview() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/deployment/overview`);
    return mockResponse(mockDeploymentOverview);
  },
};

export default deploymentApi;
