/* ============================================================================
   mockTerraformExecutionErrors.js — the error surfaced by the failing
   `terraform apply`, plus the suggested manual fix (de-conflict the subnet
   CIDR in main.tf). Also keeps a small catalog of other realistic apply
   failures for reference. MOCK ONLY.
   ========================================================================== */
import { mainTf } from './mockTerraformFiles';

/** The active execution failure used by the demo. */
export const mockTerraformExecutionError = {
  code: 'InvalidSubnet.Conflict',
  title: 'Subnet CIDR conflict',
  description:
    'aws_subnet.public[1] requested CIDR 10.0.1.0/24, which overlaps an address range already allocated in the VPC. AWS rejected the subnet creation.',
  recommendation:
    'Shift the public subnet CIDR offset in main.tf so each subnet uses a non-overlapping /24 block, then retry the execution.',
  file: 'main.tf',
  line: 30,
  phase: 'apply',
};

/** Other realistic apply failures (not used by default, kept for variety). */
export const executionErrorCatalog = [
  {
    code: 'LimitExceeded',
    title: 'Quota exceeded',
    description: 'The account has reached its limit of Elastic IP addresses in this region.',
    recommendation: 'Request a service-quota increase or release unused EIPs, then retry.',
  },
  {
    code: 'UnauthorizedOperation',
    title: 'IAM permission denied',
    description: 'The execution role is not authorized to perform rds:CreateDBInstance.',
    recommendation: 'Attach the required RDS permissions to the deployment role and retry.',
  },
  {
    code: 'InvalidParameterValue',
    title: 'Invalid region',
    description: 'The configured region "eu-west-9" does not exist.',
    recommendation: 'Set a valid region in variables.tf (e.g. eu-west-1) and retry.',
  },
];

/** The fix the manual correction workspace proposes: de-conflict subnet CIDRs. */
const correctedMainTf = mainTf.replace(
  'cidrsubnet(var.vpc_cidr, 8, count.index)',
  'cidrsubnet(var.vpc_cidr, 8, count.index + 4)'
);

export const executionFix = {
  file: 'main.tf',
  original: mainTf,
  corrected: correctedMainTf,
  note: 'Offset the public subnet CIDR blocks so they no longer overlap existing ranges.',
};

export default mockTerraformExecutionError;
