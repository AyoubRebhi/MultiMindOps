/* ============================================================================
   cicdGenerationApi.js — the Workflow Generation Agent output (Section 5): the
   generated GitHub Actions YAML and its metadata (jobs/steps/triggers).
   MOCK ONLY.
   ========================================================================== */
import {
  mockWorkflowYaml,
  mockWorkflowMeta,
  workflowFilename,
} from '@/services/mock/mockWorkflowYaml';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const cicdGenerationApi = {
  /** GET /projects/:projectId/cicd/workflow */
  async getWorkflow() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/cicd/workflow`);
    return mockResponse({
      filename: workflowFilename,
      content: mockWorkflowYaml,
      meta: mockWorkflowMeta,
    });
  },
};

export default cicdGenerationApi;
