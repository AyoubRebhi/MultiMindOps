/* ============================================================================
   mockTerraformValidationLogs.js — scripted `terraform fmt / init / validate`
   output replayed by <RealtimeLogViewer />. Two scripts: the first validation
   fails (undeclared variable), the re-validation after the fix succeeds.
   level: cmd | info | warn | error | success.
   ========================================================================== */

export const failingValidationLogs = [
  { level: 'cmd', text: '$ terraform fmt -recursive' },
  { level: 'info', text: 'main.tf' },
  { level: 'info', text: 'variables.tf' },
  { level: 'cmd', text: '$ terraform init' },
  { level: 'info', text: 'Initializing the backend...' },
  { level: 'info', text: 'Initializing provider plugins...' },
  { level: 'info', text: '- Finding hashicorp/aws versions matching "~> 5.0"...' },
  { level: 'info', text: '- Installing hashicorp/aws v5.31.0...' },
  { level: 'success', text: 'Terraform has been successfully initialized!' },
  { level: 'cmd', text: '$ terraform validate' },
  { level: 'error', text: 'Error: Reference to undeclared input variable' },
  { level: 'error', text: '  on main.tf line 70, in resource "aws_ecs_service" "app":' },
  { level: 'error', text: '  70:   desired_count = var.instance_count' },
  { level: 'error', text: 'An input variable with the name "instance_count" has not been declared.' },
  { level: 'error', text: '✖ Validation failed — 3 problem(s) found' },
];

export const successValidationLogs = [
  { level: 'cmd', text: '$ terraform fmt -recursive' },
  { level: 'info', text: 'variables.tf' },
  { level: 'cmd', text: '$ terraform init' },
  { level: 'info', text: 'Initializing provider plugins...' },
  { level: 'info', text: '- Using previously-installed hashicorp/aws v5.31.0' },
  { level: 'success', text: 'Terraform has been successfully initialized!' },
  { level: 'cmd', text: '$ terraform validate' },
  { level: 'info', text: 'Validating configuration...' },
  { level: 'success', text: 'Success! The configuration is valid.' },
];

export default { failingValidationLogs, successValidationLogs };
