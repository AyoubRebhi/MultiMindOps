/* ============================================================================
   cicdContextApi.js — the Repository Context Analysis (Section 3) and the
   Knowledge Base / RAG retrieval (Section 4) that ground the workflow
   generation. MOCK ONLY — no repo scan, no embeddings, no Qdrant.
   ========================================================================== */
import { mockContextCollection } from '@/services/mock/mockContextCollection';
import { mockRagResults } from '@/services/mock/mockRagResults';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const cicdContextApi = {
  /** GET /projects/:projectId/cicd/context */
  async getContext() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/cicd/context`);
    return mockResponse(mockContextCollection);
  },

  /** GET /projects/:projectId/cicd/rag */
  async getRagResults() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/cicd/rag`);
    return mockResponse(mockRagResults);
  },
};

export default cicdContextApi;
