/* ============================================================================
   mockPipelineExecution.js — the Pipeline Execution Center (Phase 6).
   Carries the pipeline overview (Section 1), the DAG graph nodes (Section 2)
   and the scripted real-time execution feed (Section 3). The feed is provided
   in a failing and a succeeding variant so the demo can show a deploy failure
   then a green retry. MOCK ONLY — nothing is executed, no pipeline runs.
   level: cmd | info | warn | error | success.
   ========================================================================== */

export const mockPipelineExecution = {
  name: 'Spring Boot Production Deployment',
  pipelineId: 'run-7F3A9C21',
  status: 'pending', // pending | running | completed | failed (driven by the page)
  startedAt: '2026-06-13T08:04:11Z',
  duration: '—',
  environment: 'Production',
  region: 'eu-west-1',
  awsAccount: '123456789012',
  strategy: 'Rolling Update',
  triggeredBy: 'Ayoub Rebhi',
  commit: 'a1b2c3d',
  branch: 'main',
  workflowFile: '.github/workflows/deploy.yml',

  /* Section 2 — the DAG. `failsAt` (in mockPipelineExecution defaults) marks the
     node index that fails on the first attempt; the page passes failIndex=-1 on
     a successful retry. */
  graph: [
    { key: 'checkout', label: 'Checkout Source', icon: 'fa-code-branch', duration: '3s', logs: true, artifacts: 0 },
    { key: 'build', label: 'Build Application', icon: 'fa-hammer', duration: '38s', logs: true, artifacts: 1 },
    { key: 'test', label: 'Run Unit Tests', icon: 'fa-vial-circle-check', duration: '21s', logs: true, artifacts: 1 },
    { key: 'image', label: 'Build Docker Image', icon: 'fa-docker', brand: true, duration: '24s', logs: true, artifacts: 1 },
    { key: 'push', label: 'Push Docker Image', icon: 'fa-cloud-arrow-up', duration: '12s', logs: true, artifacts: 1 },
    { key: 'infra', label: 'Deploy Infrastructure', icon: 'fa-cubes', duration: '41s', logs: true, artifacts: 2 },
    { key: 'app', label: 'Deploy Application', icon: 'fa-rocket', duration: '33s', logs: true, artifacts: 1 },
    { key: 'health', label: 'Health Checks', icon: 'fa-heart-pulse', duration: '9s', logs: true, artifacts: 0 },
  ],

  // On the first attempt the pipeline fails while deploying infrastructure.
  failIndex: 5,
};

export const pipelineRunLogsFailed = [
  { level: 'cmd', text: '$ pipeline run --env production --strategy rolling' },
  { level: 'info', text: '[checkout] Cloning repository customer-portal-api@main...' },
  { level: 'success', text: '[checkout] Checked out a1b2c3d (main).' },
  { level: 'info', text: '[build] Building Maven project (mvn -B package)...' },
  { level: 'success', text: '[build] BUILD SUCCESS — total time: 38.4 s' },
  { level: 'info', text: '[test] Running 184 unit tests...' },
  { level: 'success', text: '[test] Tests completed — 184 passed, 0 failed.' },
  { level: 'info', text: '[image] Building Docker image customer-portal-api:a1b2c3d...' },
  { level: 'success', text: '[image] Image built — 187 MB (eclipse-temurin:21-jre-alpine).' },
  { level: 'info', text: '[push] Pushing image to Amazon ECR...' },
  { level: 'success', text: '[push] Pushed → 123456789012.dkr.ecr.eu-west-1.amazonaws.com' },
  { level: 'info', text: '[infra] terraform apply — provisioning VPC, ALB, ECS, RDS...' },
  { level: 'warn', text: '[infra] aws_db_instance.postgres: still creating... (5m0s elapsed)' },
  { level: 'error', text: '[infra] Error: InsufficientDBInstanceCapacity — db.t3.medium unavailable in eu-west-1a' },
  { level: 'error', text: '[infra] terraform apply failed — exit code 1' },
  { level: 'error', text: '✖ Stage "Deploy Infrastructure" failed.' },
];

export const pipelineRunLogsSuccess = [
  { level: 'cmd', text: '$ pipeline run --env production --strategy rolling' },
  { level: 'info', text: '[checkout] Cloning repository customer-portal-api@main...' },
  { level: 'success', text: '[checkout] Checked out a1b2c3d (main).' },
  { level: 'info', text: '[build] Building Maven project (mvn -B package)...' },
  { level: 'success', text: '[build] BUILD SUCCESS — total time: 37.9 s' },
  { level: 'info', text: '[test] Running 184 unit tests...' },
  { level: 'success', text: '[test] Tests completed — 184 passed, 0 failed.' },
  { level: 'info', text: '[image] Building Docker image customer-portal-api:a1b2c3d...' },
  { level: 'success', text: '[image] Image built — 187 MB (eclipse-temurin:21-jre-alpine).' },
  { level: 'info', text: '[push] Pushing image to Amazon ECR...' },
  { level: 'success', text: '[push] Pushed → 123456789012.dkr.ecr.eu-west-1.amazonaws.com' },
  { level: 'info', text: '[infra] terraform apply — provisioning VPC, ALB, ECS, RDS...' },
  { level: 'info', text: '[infra] aws_db_instance.postgres: Creation complete (db.t3.medium, multi-az).' },
  { level: 'success', text: '[infra] Apply complete — 23 resources added, 0 changed, 0 destroyed.' },
  { level: 'info', text: '[app] Registering ECS task definition revision 24...' },
  { level: 'info', text: '[app] Updating service customer-portal-service (rolling update)...' },
  { level: 'success', text: '[app] Service is stable — 3/3 tasks running.' },
  { level: 'info', text: '[health] Probing https://customer-portal.eu-west-1.elb.amazonaws.com/actuator/health' },
  { level: 'success', text: '[health] Health check passed — 200 OK (UP).' },
  { level: 'success', text: '✔ Pipeline completed successfully — production is live.' },
];

export default mockPipelineExecution;
