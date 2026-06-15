/* ============================================================================
   mockWorkflowAnalysis.js — the single aggregated response that powers the
   Workflow Analysis Dashboard (/workflows/:projectId/analysis).

   Shape == the `WorkflowAnalysis` typedef in @/types/workflowAnalysis. This is
   the contract the future backend endpoint must satisfy:

       GET /api/workflows/{projectId}/analysis  ->  WorkflowAnalysis

   ONE object, distributed to the five panels — there are no per-panel payloads.
   MOCK ONLY: no repository is cloned or scanned here.

   `buildMockWorkflowAnalysis(projectId, { status })` lets the service stamp the
   route's projectId onto the response and simulate RUNNING / DONE / FAILED so
   every page state can be demonstrated without a backend.
   ========================================================================== */

/** @returns {import('@/types/workflowAnalysis').WorkflowAnalysis} */
function baseAnalysis() {
  return {
    // ── Section A — context header ─────────────────────────────────────────
    projectInfo: {
      id: 'prj-002',
      name: 'Customer Portal',
      repositoryUrl: 'https://github.com/cloudforge/customer-portal',
      branch: 'main',
      logoIcon: 'fa-react',
      brandIcon: true,
    },

    // ── Customer Portal panel (business-readable) ──────────────────────────
    customerPortal: {
      overview:
        'A customer-facing web portal that lets end users sign in, manage their ' +
        'account, browse their service catalog and submit support requests.',
      systemPurpose:
        'Provide a secure self-service experience for customers while shielding ' +
        'internal services behind a thin backend-for-frontend (BFF).',
      inferredDomain: 'B2C SaaS · Customer Self-Service',
      actors: ['End customers', 'Support agents', 'Account administrators'],
      description:
        'The system is a single-page React application served as static assets, ' +
        'paired with a Node/Express BFF that authenticates users, proxies to ' +
        'internal microservices and caches sessions in Redis. It is a ' +
        'read-heavy, horizontally scalable workload with no long-lived state in ' +
        'the application tier.',
    },

    // ── Code Analysis panel (technical) ────────────────────────────────────
    codeAnalysis: {
      languages: [
        { name: 'TypeScript', version: '5.4', icon: 'fa-code' },
        { name: 'JavaScript', version: 'ES2022', icon: 'fa-js', brand: true },
      ],
      frameworks: [
        { name: 'React', version: '18.2', icon: 'fa-react', brand: true },
        { name: 'Express', version: '4.19', icon: 'fa-server' },
      ],
      libraries: [
        { name: 'React Router', version: '6.24' },
        { name: 'Axios', version: '1.7' },
        { name: 'ioredis', version: '5.4' },
        { name: 'Zod', version: '3.23' },
      ],
      packageManagers: ['npm'],
      buildTools: ['Vite', 'esbuild'],
      repositoryCharacteristics: [
        { label: 'Lines of Code', value: '18,420', icon: 'fa-file-lines' },
        { label: 'Files', value: '318', icon: 'fa-folder-tree' },
        { label: 'Services', value: '3', icon: 'fa-diagram-project' },
        { label: 'Dockerfile present', value: 'No', icon: 'fa-docker', ok: false },
        { label: 'Docker Compose present', value: 'Yes', icon: 'fa-layer-group', ok: true },
        { label: 'CI/CD configured', value: 'GitHub Actions', icon: 'fa-code-branch', ok: true },
      ],
    },

    // ── Architecture Intelligence panel ────────────────────────────────────
    architecture: {
      architectureType: 'Multi-service web application (SPA + BFF)',
      model: 'MICROSERVICES',
      confidence: 92,
      observations: [
        'Frontend and backend are cleanly separable into a build stage and a slim runtime stage.',
        'The BFF is stateless — sessions are externalized to Redis, enabling horizontal scaling.',
        'No direct database coupling in the application tier; data access is via internal services.',
      ],
      suggestedPattern: 'Stateless containers behind a load balancer + managed cache',
      scalingAssumptions: [
        'Read-heavy traffic with bursty peaks during business hours.',
        'Horizontal scaling on CPU/req-count; no sticky sessions required.',
        'Target p95 latency < 300ms at the edge.',
      ],
      deploymentStrategy:
        'Rolling deployment of containerized services behind an Application Load ' +
        'Balancer, with blue/green promotion for the BFF.',
    },

    // ── Infrastructure Recommendation panel ────────────────────────────────
    infrastructureRecommendations: {
      awsServices: [
        { service: 'AWS ECS Fargate', reason: 'Run stateless containers without managing servers.', icon: 'fa-server' },
        { service: 'Application Load Balancer', reason: 'TLS termination, health checks, zero-downtime rollouts.', icon: 'fa-network-wired' },
        { service: 'Amazon ElastiCache (Redis)', reason: 'Externalized session/cache store for horizontal scaling.', icon: 'fa-database' },
      ],
      compute: [
        { service: 'ECS Fargate · 0.5 vCPU / 1GB', reason: 'Right-sized for the BFF baseline load.', icon: 'fa-microchip' },
        { service: 'Auto Scaling (2–6 tasks)', reason: 'Scale on request count to absorb peaks.', icon: 'fa-up-right-and-down-left-from-center' },
      ],
      storage: [
        { service: 'Amazon S3 + CloudFront', reason: 'Serve the SPA static build from the edge.', icon: 'fa-box-archive' },
        { service: 'ElastiCache (Redis 7)', reason: 'Low-latency session storage.', icon: 'fa-database' },
      ],
      networking: [
        { service: 'VPC with public/private subnets', reason: 'ALB in public, tasks in private subnets.', icon: 'fa-diagram-project' },
        { service: 'Security Groups', reason: 'Restrict ingress to the ALB on 443 only.', icon: 'fa-shield-halved' },
      ],
      observability: [
        { service: 'CloudWatch Logs + Metrics', reason: 'Centralized logs and per-task metrics.', icon: 'fa-chart-line' },
        { service: 'AWS X-Ray', reason: 'Trace BFF → internal service calls.', icon: 'fa-route' },
      ],
    },

    // ── Security & Containerization panel ──────────────────────────────────
    securityAnalysis: {
      score: 78,
      grade: 'B',
      summary:
        'No critical vulnerabilities. A few hardening opportunities remain ' +
        'before this image is production-ready.',
      risks: [
        { id: 'SEC-001', severity: 'high', title: 'Base image not pinned to a digest', category: 'Supply chain', detail: 'Pin to a SHA256 digest for reproducible, tamper-evident builds.' },
        { id: 'SEC-002', severity: 'medium', title: '2 transitive dependencies with advisories', category: 'Dependencies', detail: 'Both are patched in minor releases — run `npm audit fix`.' },
        { id: 'SEC-003', severity: 'medium', title: 'Container would run as root', category: 'Runtime hardening', detail: 'Add a non-root USER to limit blast radius.' },
        { id: 'SEC-004', severity: 'low', title: 'No HEALTHCHECK instruction', category: 'Observability', detail: 'Let the orchestrator detect and replace unhealthy containers.' },
      ],
      recommendations: [
        'Pin the base image to a digest and enable Dependabot/Renovate.',
        'Inject secrets at runtime via AWS Secrets Manager / SSM — never bake them into the image.',
        'Enable registry image scanning (ECR scan-on-push).',
      ],
      hardening: [
        'Add a non-root USER and a read-only root filesystem where possible.',
        'Drop all Linux capabilities the workload does not need.',
        'Set NODE_ENV=production to disable dev-only middleware.',
      ],
    },
    containerization: {
      dockerSuitability: 'High — cleanly containerizable as a single image',
      findings: [
        'SPA + BFF can be built in one Node build stage and copied into a slim runtime stage.',
        'The service binds a single port (3000), simplifying the container contract.',
        'Build is reproducible with `npm ci`.',
      ],
      imageStrategy: [
        'Multi-stage build (build → slim runtime) to keep the image under ~150 MB.',
        'Distroless or `node:18-slim` runtime base for a reduced attack surface.',
        'Expose only port 3000 and run as a non-root user.',
      ],
      notes:
        'No Dockerfile exists yet — the Container Build phase will generate one ' +
        'from these findings.',
    },

    status: 'DONE',
    lastUpdated: '2026-06-14T09:05:00Z',
    error: null,
  };
}

/**
 * Build the aggregated analysis for a given project id and simulated status.
 *
 * @param {string} projectId
 * @param {{ status?: import('@/types/workflowAnalysis').WorkflowAnalysisStatus }} [opts]
 * @returns {import('@/types/workflowAnalysis').WorkflowAnalysis}
 */
export function buildMockWorkflowAnalysis(projectId, { status = 'DONE' } = {}) {
  const data = baseAnalysis();
  data.projectInfo.id = projectId || data.projectInfo.id;
  data.status = status;
  data.lastUpdated = new Date().toISOString();
  if (status === 'FAILED') {
    data.error = 'Analysis pipeline failed while building the repository context.';
  }
  return data;
}

export const mockWorkflowAnalysis = baseAnalysis();
export default mockWorkflowAnalysis;
