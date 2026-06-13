/* ============================================================================
   mockTerraformValidationErrors.js — findings reported by the failing
   `terraform validate`, plus the suggested manual fix (declare the missing
   variable in variables.tf). MOCK ONLY.
   ========================================================================== */
import { variablesTf } from './mockTerraformFiles';

export const mockTerraformValidationErrors = [
  {
    id: 'TFV-001',
    severity: 'high',
    file: 'main.tf',
    line: 70,
    rule: 'undeclared-variable',
    message: 'Reference to undeclared input variable "instance_count" in aws_ecs_service.app.',
  },
  {
    id: 'TFV-002',
    severity: 'medium',
    file: 'providers.tf',
    line: 4,
    rule: 'provider-version',
    message: 'Provider "aws" should pin a patch version range to keep plans reproducible.',
  },
  {
    id: 'TFV-003',
    severity: 'low',
    file: 'main.tf',
    line: 27,
    rule: 'naming-style',
    message: 'Subnet tag values should follow the kebab-case naming convention.',
  },
];

/** The fix the manual correction workspace proposes: declare instance_count. */
const correctedVariablesTf =
  variablesTf.replace(/\n$/, '') +
  `

variable "instance_count" {
  type        = number
  description = "Number of ECS service tasks to run"
  default     = 2
}
`;

export const validationFix = {
  file: 'variables.tf',
  original: variablesTf,
  corrected: correctedVariablesTf,
  note: 'Declare the missing "instance_count" variable referenced by aws_ecs_service.app.',
};

export default mockTerraformValidationErrors;
