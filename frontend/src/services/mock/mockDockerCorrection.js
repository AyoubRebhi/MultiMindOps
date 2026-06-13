/* ============================================================================
   mockDockerCorrection.js — the Docker Corrector Agent's diagnosis of the
   failed build and its proposed fix. Consumed by <DockerCorrectionPanel />.
   The corrected Dockerfile itself lives in mockDockerfile.js.
   ========================================================================== */
import { mockGeneratedDockerfile, mockCorrectedDockerfile } from './mockDockerfile';

export const mockDockerCorrection = {
  projectId: 'prj-002',
  diagnosedBy: 'Docker Corrector Agent',
  confidence: 94,

  // Short, human-readable headline of why the build failed.
  errorSummary: {
    title: 'Build failed: `vite` not found during `npm run build`',
    reason:
      'The build dependency `vite` was unavailable because the image is missing a clean, deterministic install and the runtime stage ships the wrong port and privileges.',
    exitCode: 127,
    failedStep: "RUN npm run build",
  },

  // Categorized issues (the panel renders these as a checklist).
  issues: [
    {
      type: 'Missing dependency',
      icon: 'fa-cube',
      severity: 'high',
      detail: '`npm install` resolved a stale tree; switch to `npm ci` for a reproducible install from the lockfile.',
    },
    {
      type: 'Invalid command',
      icon: 'fa-terminal',
      severity: 'medium',
      detail: 'Runtime stage copies dev `node_modules`; install production deps with `npm ci --omit=dev` instead.',
    },
    {
      type: 'Port mismatch',
      icon: 'fa-plug',
      severity: 'high',
      detail: 'Dockerfile exposes 8080 but the BFF binds 3000 — health checks and the ALB target would fail.',
    },
    {
      type: 'Runtime hardening',
      icon: 'fa-user-shield',
      severity: 'low',
      detail: 'Container runs as root and omits NODE_ENV; add a non-root `USER` and `ENV NODE_ENV=production`.',
    },
  ],

  // AI explanation of the proposed fix (one line summary).
  suggestedFix:
    'Use `npm ci` in both stages, install prod-only dependencies in the runtime image, expose port 3000, set NODE_ENV=production and drop to a non-root user.',

  // Side-by-side comparison source.
  originalDockerfile: mockGeneratedDockerfile,
  correctedDockerfile: mockCorrectedDockerfile,
};

export default mockDockerCorrection;
