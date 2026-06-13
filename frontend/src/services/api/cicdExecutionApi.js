/* ============================================================================
   cicdExecutionApi.js — simulates running the compiled workflow locally with
   nektos/act (Section 9). Outcome is attempt-driven so the demo shows an apply
   failure (ECR auth) then a successful retry. It also resolves the final
   pipeline result for Section 10. MOCK ONLY — nothing executes.
   ========================================================================== */
import {
  failingExecutionLogs,
  successExecutionLogs,
} from '@/services/mock/mockExecutionSimulationLogs';
import {
  mockPipelineSuccess,
  mockPipelineFailed,
} from '@/services/mock/mockPipelineResults';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const cicdExecutionApi = {
  /**
   * POST /projects/:projectId/cicd/simulate
   * @param {number} attempt 1-based — attempt 1 fails, attempt 2+ succeeds.
   */
  async runExecution(attempt = 1) {
    // if (!USE_MOCK) return apiClient.post(`/projects/${projectId}/cicd/simulate`);
    const willFail = attempt <= 1;
    return mockResponse({
      attempt,
      logs: willFail ? failingExecutionLogs : successExecutionLogs,
      status: willFail ? 'failed' : 'completed',
      result: willFail ? mockPipelineFailed : mockPipelineSuccess,
    });
  },
};

export default cicdExecutionApi;
