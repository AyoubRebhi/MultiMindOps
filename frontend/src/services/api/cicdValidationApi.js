/* ============================================================================
   cicdValidationApi.js — simulates schema validation of the generated workflow
   (Section 6). Outcome is attempt-driven so the demo shows the failure
   (findings) then a passing re-validation after the fix. MOCK ONLY.
   ========================================================================== */
import {
  failingValidationLogs,
  successValidationLogs,
} from '@/services/mock/mockSchemaValidationLogs';
import {
  mockSchemaValidationErrors,
  validationFix,
} from '@/services/mock/mockSchemaValidationErrors';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const cicdValidationApi = {
  /**
   * POST /projects/:projectId/cicd/validate
   * @param {number} attempt 1-based — attempt 1 fails, attempt 2+ passes.
   */
  async runValidation(attempt = 1) {
    // if (!USE_MOCK) return apiClient.post(`/projects/${projectId}/cicd/validate`);
    const willFail = attempt <= 1;
    return mockResponse({
      attempt,
      logs: willFail ? failingValidationLogs : successValidationLogs,
      status: willFail ? 'failed' : 'completed',
      findings: willFail ? mockSchemaValidationErrors : [],
      fix: willFail ? validationFix : null,
    });
  },
};

export default cicdValidationApi;
