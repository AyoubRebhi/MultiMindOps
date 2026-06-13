/* ============================================================================
   mockPipelineResults.js — the final outcome of the CI/CD phase (Section 10)
   shown by <PipelineResultCard />. Success carries the pipeline summary +
   metadata; failure carries the failed stage, reason and suggested action.
   MOCK ONLY.
   ========================================================================== */

export const mockPipelineSuccess = {
  status: 'completed',
  title: 'Pipeline Generated Successfully',
  workflowFile: '.github/workflows/deploy.yml',
  executionDuration: '1m 52s',
  jobsCreated: 2,
  stepsCreated: 11,
  securityScore: 96,
  securityGrade: 'A',
  checksum: 'sha256:9f3c1d7a…6701bd2',
  generatedAt: '2026-06-13T08:08:00Z',
};

export const mockPipelineFailed = {
  status: 'failed',
  title: 'Pipeline Generation Failed',
  failedStage: 'Execution Simulation',
  failureReason:
    'The deploy job failed while pushing the image — ECR authentication was rejected.',
  suggestedAction:
    'Configure the AWS_DEPLOY_ROLE_ARN secret with ECR push permissions, then re-run the execution.',
  failedAt: '2026-06-13T08:07:00Z',
};

export default { mockPipelineSuccess, mockPipelineFailed };
