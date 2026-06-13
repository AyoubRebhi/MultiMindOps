/* ============================================================================
   infrastructureApi.js — the deployed infrastructure for the Infrastructure
   Dashboard (Phase 7): category summary, resource inventory, architecture
   topology and deployment metrics. MOCK ONLY — no cloud resources exist.
   ========================================================================== */
import {
  infrastructureSummary,
  infrastructureInventory,
} from '@/services/mock/mockInfrastructureResources';
import { mockInfrastructureTopology } from '@/services/mock/mockInfrastructureTopology';
import { mockDeploymentMetrics } from '@/services/mock/mockDeploymentMetrics';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const infrastructureApi = {
  /** GET /projects/:projectId/infrastructure/summary */
  async getSummary() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/infrastructure/summary`);
    return mockResponse(infrastructureSummary);
  },

  /** GET /projects/:projectId/infrastructure/resources */
  async getInventory() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/infrastructure/resources`);
    return mockResponse(infrastructureInventory);
  },

  /** GET /projects/:projectId/infrastructure/topology */
  async getTopology() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/infrastructure/topology`);
    return mockResponse(mockInfrastructureTopology);
  },

  /** GET /projects/:projectId/infrastructure/metrics */
  async getMetrics() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/infrastructure/metrics`);
    return mockResponse(mockDeploymentMetrics);
  },
};

export default infrastructureApi;
