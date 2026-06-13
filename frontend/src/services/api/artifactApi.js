/* ============================================================================
   artifactApi.js — generated artifacts. Two surfaces share this service:
     · the Artifacts page (Dockerfile, K8s, Helm, ...), and
     · the pipeline run artifacts browsed in <ArtifactExplorer /> (Section 5 of
       the Execution Center, Section 7 of the Infrastructure Dashboard).
   MOCK ONLY.
   ========================================================================== */
import { mockArtifacts } from '@/services/mock/mockArtifacts';
import { mockPipelineArtifacts } from '@/services/mock/mockPipelineArtifacts';
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

  /** GET /projects/:projectId/pipeline/artifacts — artifacts from the run. */
  async listPipelineArtifacts() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/pipeline/artifacts`);
    return mockResponse(mockPipelineArtifacts);
  },

  /** GET /projects/:projectId/pipeline/artifacts/:id */
  async getPipelineArtifact(id) {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/pipeline/artifacts/${id}`);
    const art = mockPipelineArtifacts.find((a) => a.id === id);
    return art ? mockResponse(art) : mockError(`Artifact "${id}" not found`);
  },
};

export default artifactApi;
