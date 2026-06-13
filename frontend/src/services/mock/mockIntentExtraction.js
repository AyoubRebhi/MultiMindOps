/* ============================================================================
   mockIntentExtraction.js — output of the CI/CD Request Analysis + Intent
   Extraction agents for the demo project (a Spring Boot service deploying to
   AWS ECS). `mockRequestAnalysis` drives Section 1 (request + detected stack)
   and `mockIntentExtraction` drives Section 2 (the AI reasoning card).
   MOCK ONLY — no repo is cloned, no LLM is called.
   ========================================================================== */

export const mockRequestAnalysis = {
  originalRequest:
    'Generate a production-grade GitHub Actions pipeline that builds my Spring Boot service with Maven, packages it as a Docker image, pushes it to Amazon ECR and deploys to ECS Fargate on every push to main.',
  repository: {
    name: 'customer-portal-api',
    url: 'github.com/cloudforge/customer-portal-api',
    branch: 'main',
    visibility: 'private',
    lastCommit: '2026-06-13T07:55:00Z',
  },
  // Detected technology stack
  techStack: [
    { name: 'Java', version: '21 (Temurin)', icon: 'fa-java', brand: true },
    { name: 'Spring Boot', version: '3.5.0', icon: 'fa-leaf' },
    { name: 'Maven', version: '3.9.6', icon: 'fa-cube' },
    { name: 'Docker', version: 'available', icon: 'fa-docker', brand: true },
    { name: 'PostgreSQL', version: '16', icon: 'fa-database' },
  ],
  framework: 'Spring Boot 3.5 · Web · Actuator · Data JPA',
  runtimeVersions: ['Java 21 LTS', 'Maven 3.9', 'Node 20 (tooling)'],
  // The "signal" pills shown in the request analysis card
  signals: [
    { label: 'Java 21', icon: 'fa-java', brand: true, tone: 'ok' },
    { label: 'Spring Boot 3.5', icon: 'fa-leaf', tone: 'ok' },
    { label: 'Docker Available', icon: 'fa-docker', brand: true, tone: 'ok' },
    { label: 'AWS Target Platform', icon: 'fa-aws', brand: true, tone: 'info' },
  ],
  agentConfidence: 94,
  intentType: 'CI/CD Pipeline Generation',
  pipelineComplexity: 'Moderate',
};

export const mockIntentExtraction = {
  agent: 'Intent Extraction Agent',
  model: 'gpt-5-mini',
  intent:
    'Create and deploy a containerized CI/CD pipeline for a Spring Boot service targeting AWS ECS Fargate.',
  requestType: 'BUILD_AND_DEPLOY',
  confidenceScore: 94,
  reasoning: [
    'User explicitly mentions a "GitHub Actions pipeline" → CI/CD generation intent.',
    'Maven build + Spring Boot packaging → a JVM build & test job is required.',
    '"Docker image" + "push to ECR" → a container build & registry push stage.',
    '"deploy to ECS Fargate" → an AWS ECS deployment stage with a task definition.',
    '"on every push to main" → a push trigger scoped to the main branch.',
  ],
  detectedRequirements: [
    { label: 'Maven build & test', icon: 'fa-cube', met: true },
    { label: 'Docker image build', icon: 'fa-docker', brand: true, met: true },
    { label: 'Push to Amazon ECR', icon: 'fa-aws', brand: true, met: true },
    { label: 'Deploy to ECS Fargate', icon: 'fa-server', met: true },
    { label: 'Trigger on push to main', icon: 'fa-code-branch', met: true },
  ],
  deploymentTarget: {
    provider: 'AWS',
    service: 'ECS Fargate',
    region: 'eu-west-1',
    registry: 'Amazon ECR',
    icon: 'fa-aws',
  },
};

export default { mockRequestAnalysis, mockIntentExtraction };
