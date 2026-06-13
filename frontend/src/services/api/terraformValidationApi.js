/* ============================================================================
   terraformValidationApi.js — simulates `terraform fmt / init / validate`.
   MOCK ONLY — nothing runs. Outcome is attempt-driven so the demo shows the
   failure (findings) then a passing re-validation after the fix.
   ========================================================================== */
import {
  failingValidationLogs,
  successValidationLogs,
} from '@/services/mock/mockTerraformValidationLogs';
import {
  mockTerraformValidationErrors,
  validationFix,
} from '@/services/mock/mockTerraformValidationErrors';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const terraformValidationApi = {
  /**
   * POST /projects/:projectId/terraform/validate
   * @param {number} attempt 1-based — attempt 1 fails, attempt 2+ succeeds.
   */
  async runValidation(attempt = 1) {
    // if (!USE_MOCK) return apiClient.post(`/projects/${projectId}/terraform/validate`);
    const willFail = attempt <= 1;
    return mockResponse({
      attempt,
      logs: willFail ? failingValidationLogs : successValidationLogs,
      status: willFail ? 'failed' : 'completed',
      findings: willFail ? mockTerraformValidationErrors : [],
      fix: willFail ? validationFix : null,
    });
  },
};

export default terraformValidationApi;
