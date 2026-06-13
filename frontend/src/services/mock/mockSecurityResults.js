/* ============================================================================
   mockSecurityResults.js — output of the Security Guard Agent for the demo
   project. Static, illustrative findings only — no real scanning happens.
   ========================================================================== */

export const mockSecurityResults = {
  projectId: 'prj-002',
  // 0–100; drives the score ring + grade
  score: 78,
  grade: 'B',
  scannedAt: '2026-06-12T09:05:00Z',
  summary:
    'No critical vulnerabilities detected. A few hardening opportunities remain before this image is production-ready — mostly around dependency pinning and secret handling.',

  // Quick tallies shown as small stat chips
  counts: { critical: 0, high: 1, medium: 2, low: 3 },

  findings: [
    {
      id: 'SEC-001',
      severity: 'high',
      title: 'Base image not pinned to a digest',
      detail:
        'Dockerfile references `node:18-alpine` by tag. Pin to a SHA256 digest to guarantee reproducible, tamper-evident builds.',
      category: 'Supply chain',
      icon: 'fa-box',
    },
    {
      id: 'SEC-002',
      severity: 'medium',
      title: '2 transitive dependencies with known advisories',
      detail:
        'Run `npm audit fix` — both advisories are patched in minor releases and do not require breaking changes.',
      category: 'Dependencies',
      icon: 'fa-cubes',
    },
    {
      id: 'SEC-003',
      severity: 'medium',
      title: 'Container would run as root',
      detail:
        'The runtime stage does not drop privileges. Add a non-root `USER` to limit blast radius if the process is compromised.',
      category: 'Runtime hardening',
      icon: 'fa-user-shield',
    },
    {
      id: 'SEC-004',
      severity: 'low',
      title: 'No HEALTHCHECK instruction',
      detail:
        'Add a HEALTHCHECK so the orchestrator can detect and replace unhealthy containers automatically.',
      category: 'Observability',
      icon: 'fa-heart-pulse',
    },
  ],

  warnings: [
    'Session secret is read from an environment variable — ensure it is injected from a secrets manager, not baked into the image.',
    'Source maps are emitted in the production build; consider stripping them to avoid leaking source.',
  ],

  recommendations: [
    { text: 'Pin the base image to a digest and enable Dependabot/renovate.', icon: 'fa-shield-halved' },
    { text: 'Add a non-root USER and a read-only root filesystem where possible.', icon: 'fa-user-lock' },
    { text: 'Inject secrets at runtime via AWS Secrets Manager / SSM, never in the image.', icon: 'fa-key' },
    { text: 'Enable image scanning in the registry (ECR scan-on-push).', icon: 'fa-magnifying-glass' },
  ],
};

export default mockSecurityResults;
