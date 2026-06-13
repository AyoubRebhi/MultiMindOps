/* ============================================================================
   analysisApi.js — Code Analysis Agent + Security Guard Agent results that feed
   the Project Analysis page. MOCK ONLY (no repo is cloned or scanned).
   ========================================================================== */
import { mockAnalysisResults } from '@/services/mock/mockAnalysisResults';
import { mockSecurityResults } from '@/services/mock/mockSecurityResults';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const analysisApi = {
  /** GET /projects/:projectId/analysis — code analysis agent output. */
  async getAnalysis(projectId) {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/analysis`);
    return mockResponse({ ...mockAnalysisResults, projectId: projectId || mockAnalysisResults.projectId });
  },

  /** GET /projects/:projectId/security — security guard agent output. */
  async getSecurity(projectId) {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/security`);
    return mockResponse({ ...mockSecurityResults, projectId: projectId || mockSecurityResults.projectId });
  },
};

export default analysisApi;
