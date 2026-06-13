/* ============================================================================
   mockAnalysisResults.js — output of the Code Analysis Agent for the demo
   project (Customer Portal). Shape mirrors what the backend analysis endpoint
   is expected to return so the ProjectAnalysisPage can be built against a
   realistic contract. MOCK ONLY — no real repo is ever cloned or scanned.
   ========================================================================== */

export const mockAnalysisResults = {
  projectId: 'prj-002',
  // ---- Project summary (top card) --------------------------------------
  project: {
    name: 'Customer Portal',
    repoUrl: 'github.com/cloudforge/customer-portal',
    branch: 'main',
    language: 'JavaScript / TypeScript',
    framework: 'React 18 (Vite) + Node.js BFF',
    runtime: 'Node.js 18 (alpine)',
    repoSize: '24.8 MB',
    files: 318,
    lastCommit: '2026-06-12T08:42:00Z',
  },

  // ---- Section 1: Code Analysis Results --------------------------------
  detectedStack: [
    { name: 'Node.js', version: '18.x', icon: 'fa-node-js', brand: true, kind: 'runtime' },
    { name: 'React', version: '18.2', icon: 'fa-react', brand: true, kind: 'frontend' },
    { name: 'Vite', version: '5.2', icon: 'fa-bolt', kind: 'bundler' },
    { name: 'Express', version: '4.19', icon: 'fa-server', kind: 'backend' },
    { name: 'Redis', version: '7.2', icon: 'fa-database', kind: 'cache' },
    { name: 'npm', version: '10.x', icon: 'fa-cube', kind: 'package-manager' },
  ],
  architecture: {
    type: 'Multi-service web application',
    pattern: 'SPA frontend + Backend-for-Frontend (BFF)',
    confidence: 92,
    summary:
      'A React single-page app served as static assets, paired with a thin Node/Express BFF that proxies to internal services and uses Redis for session storage. Cleanly separable into a build stage and a slim runtime image.',
  },
  services: [
    {
      name: 'web',
      role: 'Frontend SPA',
      icon: 'fa-react',
      brand: true,
      port: 3000,
      build: 'Vite static build → served by BFF',
      health: '/healthz',
    },
    {
      name: 'bff',
      role: 'Node/Express API gateway',
      icon: 'fa-server',
      port: 3000,
      build: 'node dist/server.js',
      health: '/api/health',
    },
    {
      name: 'redis',
      role: 'Session / cache store',
      icon: 'fa-database',
      port: 6379,
      build: 'managed (ElastiCache)',
      health: 'PING',
    },
  ],
  deploymentRecommendations: [
    {
      title: 'Containerize as a single multi-stage image',
      detail:
        'Build the SPA and BFF in one Node build stage, then copy only the dist output and production dependencies into a slim runtime stage.',
      icon: 'fa-layer-group',
      severity: 'recommended',
    },
    {
      title: 'Run behind an Application Load Balancer',
      detail:
        'Terminate TLS at the ALB and forward to the container on port 3000; enables health checks and zero-downtime rollouts.',
      icon: 'fa-network-wired',
      severity: 'recommended',
    },
    {
      title: 'Externalize sessions to managed Redis',
      detail:
        'Use ElastiCache rather than an in-container Redis so the service can scale horizontally without sticky sessions.',
      icon: 'fa-database',
      severity: 'recommended',
    },
  ],
  containerizationRecommendations: [
    { text: 'Use a multi-stage build to keep the runtime image under ~150 MB.', icon: 'fa-circle-check' },
    { text: 'Install dependencies with `npm ci` for reproducible builds.', icon: 'fa-circle-check' },
    { text: 'Expose port 3000 (the port the BFF actually binds).', icon: 'fa-circle-check' },
    { text: 'Run as a non-root user in the runtime stage.', icon: 'fa-circle-check' },
    { text: 'Set NODE_ENV=production to disable dev-only middleware.', icon: 'fa-circle-check' },
  ],
};

export default mockAnalysisResults;
