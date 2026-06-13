/* ============================================================================
   executionApi.js — the Pipeline Execution Center (Phase 6). Serves the
   pipeline overview + DAG and runs the pipeline. The run is attempt-driven so
   the demo shows an infrastructure failure (Failure Recovery section) then a
   green retry. MOCK ONLY — no pipeline executes, nothing is deployed.
   ========================================================================== */
import {
  mockPipelineExecution,
  pipelineRunLogsFailed,
  pipelineRunLogsSuccess,
} from '@/services/mock/mockPipelineExecution';
import {
  mockPipelineStages,
  mockPipelineStagesFailed,
} from '@/services/mock/mockPipelineStages';
import {
  mockExecutionResultSuccess,
  mockExecutionResultFailed,
} from '@/services/mock/mockDeploymentResults';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const executionApi = {
  /** GET /projects/:projectId/pipeline — overview + DAG graph. */
  async getOverview() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/pipeline`);
    return mockResponse(mockPipelineExecution);
  },

  /**
   * POST /projects/:projectId/pipeline/run
   * @param {number} attempt 1-based — attempt 1 fails at the Infrastructure
   *   stage, attempt 2+ runs the full pipeline to a green deploy.
   * Returns the scripted logs, the graph fail index, the resolved stages and
   * the final execution result.
   */
  async runExecution(attempt = 1) {
    // if (!USE_MOCK) return apiClient.post(`/projects/${projectId}/pipeline/run`);
    const willFail = attempt <= 1;
    return mockResponse(
      {
        attempt,
        status: willFail ? 'failed' : 'completed',
        logs: willFail ? pipelineRunLogsFailed : pipelineRunLogsSuccess,
        failIndex: willFail ? mockPipelineExecution.failIndex : -1,
        stages: willFail ? mockPipelineStagesFailed : mockPipelineStages,
        result: willFail ? mockExecutionResultFailed : mockExecutionResultSuccess,
      },
      { minMs: 250, maxMs: 600 },
    );
  },
};

export default executionApi;
