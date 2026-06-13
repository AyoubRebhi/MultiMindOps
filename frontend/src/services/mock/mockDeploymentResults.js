/* ============================================================================
   mockDeploymentResults.js — two outcomes used across the final phases:
     · mockExecutionResult{Success,Failed} → Section 8 of the Execution Center,
       rendered by <ExecutionResultCard />.
     · mockDeploymentOverview              → Section 1 of the Infrastructure
       Dashboard, rendered by <DeploymentOverviewCard /> (success banner +
       overview fields).
   MOCK ONLY — nothing was actually deployed.
   ========================================================================== */

export const mockExecutionResultSuccess = {
  status: 'completed',
  title: 'Execution Successful',
  subtitle: 'The pipeline ran end-to-end and production is live.',
  totalDuration: '3m 01s',
  completedStages: 5,
  failedStages: 0,
  artifactsGenerated: 7,
  deploymentTime: '2026-06-13T08:07:12Z',
};

export const mockExecutionResultFailed = {
  status: 'failed',
  title: 'Execution Failed',
  subtitle: 'The pipeline stopped while provisioning infrastructure.',
  totalDuration: '6m 41s',
  completedStages: 2,
  failedStages: 1,
  artifactsGenerated: 3,
  deploymentTime: null,
  failedStage: 'Infrastructure Stage',
  failureReason:
    'terraform apply failed — InsufficientDBInstanceCapacity: db.t3.medium is unavailable in eu-west-1a.',
  recommendedFix:
    'Retry the Infrastructure stage in a different AZ, or change instance_class to db.t3.large in rds.tf, then re-run.',
};

export const mockDeploymentOverview = {
  deploymentStatus: 'deployed',
  bannerTitle: 'Infrastructure Successfully Deployed',
  bannerSubtitle:
    'customer-portal-api is live in Production on AWS · eu-west-1. 23 resources provisioned with zero failures.',
  environment: 'Production',
  region: 'eu-west-1',
  regionLabel: 'EU (Ireland)',
  provider: 'AWS',
  workspace: 'Demo Workspace',
  deploymentDate: '2026-06-13T08:07:12Z',
  deploymentDuration: '1m 23s',
  endpoint: 'https://customer-portal.eu-west-1.elb.amazonaws.com',
};

export default {
  mockExecutionResultSuccess,
  mockExecutionResultFailed,
  mockDeploymentOverview,
};
