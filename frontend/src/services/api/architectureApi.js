/* ============================================================================
   architectureApi.js — proposed architecture plans and their options.
   ========================================================================== */
import { mockArchitecturePlans } from '@/services/mock/mockArchitecturePlans';
import { mockResponse, mockError } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const architectureApi = {
  /** GET /architecture-plans */
  async list() {
    // if (!USE_MOCK) return apiClient.get('/architecture-plans');
    return mockResponse(mockArchitecturePlans);
  },

  /** GET /architecture-plans/:id */
  async getById(id) {
    // if (!USE_MOCK) return apiClient.get(`/architecture-plans/${id}`);
    const plan = mockArchitecturePlans.find((p) => p.id === id);
    return plan ? mockResponse(plan) : mockError(`Plan "${id}" not found`);
  },

  /** GET /projects/:projectId/architecture-plans */
  async listByProject(projectId) {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/architecture-plans`);
    return mockResponse(
      mockArchitecturePlans.filter((p) => p.projectId === projectId)
    );
  },
};

export default architectureApi;
