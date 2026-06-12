/* ============================================================================
   artifactApi.js — generated artifacts (Dockerfile, K8s, Helm, ...).
   ========================================================================== */
import { mockArtifacts } from '@/services/mock/mockArtifacts';
import { mockResponse, mockError } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const artifactApi = {
  /** GET /artifacts */
  async list() {
    // if (!USE_MOCK) return apiClient.get('/artifacts');
    return mockResponse(mockArtifacts);
  },

  /** GET /artifacts/:id */
  async getById(id) {
    // if (!USE_MOCK) return apiClient.get(`/artifacts/${id}`);
    const art = mockArtifacts.find((a) => a.id === id);
    return art ? mockResponse(art) : mockError(`Artifact "${id}" not found`);
  },

  /** GET /projects/:projectId/artifacts */
  async listByProject(projectId) {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/artifacts`);
    return mockResponse(mockArtifacts.filter((a) => a.projectId === projectId));
  },
};

export default artifactApi;
