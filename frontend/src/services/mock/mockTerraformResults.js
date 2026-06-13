/* ============================================================================
   mockTerraformResults.js — the final outcome of the Terraform phase shown by
   <TerraformDeploymentResult />. Success carries the infra summary + metadata;
   failure carries the reason, last error and suggested next action. MOCK ONLY.
   ========================================================================== */
import { totalResourceCount } from './mockTerraformResources';

export const mockTerraformSuccessResult = {
  status: 'completed',
  title: 'Terraform Deployment Successful',
  environment: 'staging',
  region: 'eu-west-1',
  duration: '5m 47s',
  resourcesCreated: totalResourceCount,
  generatedAt: '2026-06-13T10:24:00Z',
  stateVersion: 7,
};

export const mockTerraformFailedResult = {
  status: 'failed',
  title: 'Terraform Deployment Failed',
  environment: 'staging',
  region: 'eu-west-1',
  failureReason: 'Apply failed while creating networking resources.',
  lastError: 'InvalidSubnet.Conflict — CIDR 10.0.1.0/24 conflicts with another subnet in the VPC.',
  suggestedAction: 'Resolve the subnet CIDR overlap in main.tf, then retry the execution.',
  partialResourcesCreated: 2,
  failedAt: '2026-06-13T10:11:00Z',
};

export default { mockTerraformSuccessResult, mockTerraformFailedResult };
