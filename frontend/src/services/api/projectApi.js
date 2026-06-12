/* ============================================================================
   projectApi.js — projects resource.
   Returns mock data for now. The commented lines show the real endpoint each
   function will hit once USE_MOCK is turned off.
   ========================================================================== */
import { mockProjects } from '@/services/mock/mockProjects';
import { mockResponse, mockError } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const projectApi = {
  /** GET /projects */
  async list() {
    // if (!USE_MOCK) return apiClient.get('/projects');
    return mockResponse(mockProjects);
  },

  /** GET /projects/:id */
  async getById(id) {
    // if (!USE_MOCK) return apiClient.get(`/projects/${id}`);
    const project = mockProjects.find((p) => p.id === id);
    return project
      ? mockResponse(project)
      : mockError(`Project "${id}" not found`);
  },

  /** POST /projects */
  async create(payload) {
    // if (!USE_MOCK) return apiClient.post('/projects', payload);
    return mockResponse({
      id: `prj-${Date.now()}`,
      status: 'draft',
      progress: 0,
      ...payload,
    });
  },
};

export default projectApi;
