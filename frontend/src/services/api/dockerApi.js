/* ============================================================================
   dockerApi.js — Docker phase: generated Dockerfile, build log streams, the
   corrector diagnosis and the final build result. MOCK ONLY — nothing is built.

   The build log streams are returned as plain arrays; the <RealtimeLogViewer />
   component replays them line-by-line to simulate a websocket feed. The build
   *outcome* is driven by the attempt number so the demo tells a full story:
   attempt 1 fails (showcasing the Docker Corrector), attempt 2+ succeeds.
   ========================================================================== */
import {
  mockGeneratedDockerfile,
  mockCorrectedDockerfile,
  mockDockerfileMeta,
} from '@/services/mock/mockDockerfile';
import {
  failingBuildLogs,
  successBuildLogs,
} from '@/services/mock/mockDockerBuildLogs';
import { mockDockerCorrection } from '@/services/mock/mockDockerCorrection';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

const failedResult = {
  status: 'failed',
  reason: 'Build dependency `vite` not found during `npm run build` (exit code 127).',
  failedStep: 'RUN npm run build',
  recommendation:
    'The Docker Corrector Agent has proposed a fix — review and approve it, then rebuild.',
  duration: '18s',
};

const successResult = {
  status: 'completed',
  imageName: 'customer-portal:latest',
  imageDigest: 'sha256:9f3c2a8b7d61',
  imageSize: '142 MB',
  duration: '42s',
  layers: 13,
  builtAt: '2026-06-12T09:18:00Z',
};

export const dockerApi = {
  /** GET /projects/:projectId/dockerfile — the AI-generated Dockerfile. */
  async getDockerfile(projectId) {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/dockerfile`);
    return mockResponse({
      ...mockDockerfileMeta,
      projectId: projectId || mockDockerfileMeta.projectId,
      content: mockGeneratedDockerfile,
      correctedContent: mockCorrectedDockerfile,
    });
  },

  /** PUT /projects/:projectId/dockerfile — persist an edited Dockerfile. */
  async saveDockerfile(projectId, content) {
    // if (!USE_MOCK) return apiClient.put(`/projects/${projectId}/dockerfile`, { content });
    return mockResponse({ saved: true, content }, { minMs: 200, maxMs: 400 });
  },

  /**
   * POST /projects/:projectId/build — "start" a build. Returns the scripted log
   * stream for this attempt plus the outcome the stream resolves to.
   * @param {number} attempt 1-based attempt counter (1 fails, 2+ succeeds)
   */
  async startBuild(projectId, attempt = 1) {
    // if (!USE_MOCK) return apiClient.post(`/projects/${projectId}/build`, { attempt });
    const willFail = attempt <= 1;
    return mockResponse({
      buildId: `build-${Date.now()}`,
      attempt,
      logs: willFail ? failingBuildLogs : successBuildLogs,
      result: willFail ? failedResult : successResult,
    });
  },

  /** GET /projects/:projectId/build/correction — corrector diagnosis + fix. */
  async getCorrection(projectId) {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/build/correction`);
    return mockResponse({ ...mockDockerCorrection, projectId: projectId || mockDockerCorrection.projectId });
  },
};

export default dockerApi;
