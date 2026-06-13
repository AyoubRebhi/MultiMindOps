/* ============================================================================
   terraformExecutionApi.js — simulates `terraform plan / apply`. MOCK ONLY —
   no AWS, no apply. Outcome is attempt-driven so the demo shows an apply
   failure (subnet conflict) then a successful retry after the fix.
   ========================================================================== */
import {
  failingExecutionLogs,
  successExecutionLogs,
} from '@/services/mock/mockTerraformExecutionLogs';
import {
  mockTerraformExecutionError,
  executionFix,
} from '@/services/mock/mockTerraformExecutionErrors';
import {
  mockTerraformSuccessResult,
  mockTerraformFailedResult,
} from '@/services/mock/mockTerraformResults';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const terraformExecutionApi = {
  /**
   * POST /projects/:projectId/terraform/apply
   * @param {number} attempt 1-based — attempt 1 fails, attempt 2+ succeeds.
   */
  async runExecution(attempt = 1) {
    // if (!USE_MOCK) return apiClient.post(`/projects/${projectId}/terraform/apply`);
    const willFail = attempt <= 1;
    return mockResponse({
      attempt,
      logs: willFail ? failingExecutionLogs : successExecutionLogs,
      status: willFail ? 'failed' : 'completed',
      error: willFail ? mockTerraformExecutionError : null,
      fix: willFail ? executionFix : null,
      result: willFail ? mockTerraformFailedResult : mockTerraformSuccessResult,
    });
  },
};

export default terraformExecutionApi;
