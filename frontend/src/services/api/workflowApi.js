/* ============================================================================
   workflowApi.js — workflow runs resource (and their phase timelines).
   ========================================================================== */
import { mockWorkflows } from '@/services/mock/mockWorkflows';
import { mockResponse, mockError } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const workflowApi = {
  /** GET /workflows */
  async list() {
    // if (!USE_MOCK) return apiClient.get('/workflows');
    return mockResponse(mockWorkflows);
  },

  /** GET /workflows/:id */
  async getById(id) {
    // if (!USE_MOCK) return apiClient.get(`/workflows/${id}`);
    const wf = mockWorkflows.find((w) => w.id === id);
    return wf ? mockResponse(wf) : mockError(`Workflow "${id}" not found`);
  },

  /** GET /projects/:projectId/workflows */
  async listByProject(projectId) {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/workflows`);
    return mockResponse(mockWorkflows.filter((w) => w.projectId === projectId));
  },
};

export default workflowApi;
