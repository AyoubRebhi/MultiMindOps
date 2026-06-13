/* ============================================================================
   cicdCompilationApi.js — simulates the Workflow Compiler (Section 8): pins
   actions to immutable SHAs, computes a checksum and emits workflow.lock.
   MOCK ONLY.
   ========================================================================== */
import { mockCompilationResult } from '@/services/mock/mockCompilationResults';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const cicdCompilationApi = {
  /** POST /projects/:projectId/cicd/compile */
  async compile() {
    // if (!USE_MOCK) return apiClient.post(`/projects/${projectId}/cicd/compile`);
    return mockResponse(mockCompilationResult, { minMs: 600, maxMs: 1100 });
  },
};

export default cicdCompilationApi;
