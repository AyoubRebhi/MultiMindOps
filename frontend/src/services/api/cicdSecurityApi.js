/* ============================================================================
   cicdSecurityApi.js — simulates the Security Guardrails Audit (Section 7).
   Outcome is attempt-driven so the demo shows the critical findings (hardcoded
   key / unverified action / excessive perms) then a clean re-audit after the
   fix. MOCK ONLY — nothing is scanned.
   ========================================================================== */
import {
  mockSecurityAuditFailed,
  mockSecurityAuditPassed,
} from '@/services/mock/mockSecurityAudit';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const cicdSecurityApi = {
  /**
   * POST /projects/:projectId/cicd/security-audit
   * @param {number} attempt 1-based — attempt 1 fails, attempt 2+ passes.
   */
  async runAudit(attempt = 1) {
    // if (!USE_MOCK) return apiClient.post(`/projects/${projectId}/cicd/security-audit`);
    const willFail = attempt <= 1;
    return mockResponse(willFail ? mockSecurityAuditFailed : mockSecurityAuditPassed);
  },
};

export default cicdSecurityApi;
