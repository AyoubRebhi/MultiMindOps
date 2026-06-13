/* ============================================================================
   mockTerraformExecutionLogs.js — scripted `terraform plan / apply` output
   replayed by <RealtimeLogViewer />. The first apply fails (subnet conflict),
   the retry after the fix provisions everything successfully.
   ========================================================================== */

export const failingExecutionLogs = [
  { level: 'cmd', text: '$ terraform plan -out=tfplan' },
  { level: 'info', text: 'Refreshing state...' },
  { level: 'info', text: 'Terraform will perform the following actions:' },
  { level: 'info', text: 'Plan: 14 to add, 0 to change, 0 to destroy.' },
  { level: 'cmd', text: '$ terraform apply "tfplan"' },
  { level: 'info', text: 'aws_vpc.main: Creating...' },
  { level: 'info', text: 'aws_vpc.main: Creation complete after 2s [id=vpc-0a1b2c3d4e]' },
  { level: 'info', text: 'aws_internet_gateway.main: Creation complete after 1s' },
  { level: 'info', text: 'aws_subnet.public[0]: Creating...' },
  { level: 'info', text: 'aws_subnet.public[1]: Creating...' },
  { level: 'error', text: 'Error: creating EC2 Subnet: InvalidSubnet.Conflict' },
  { level: 'error', text: '  the CIDR "10.0.1.0/24" conflicts with another subnet in the VPC' },
  { level: 'error', text: '  with aws_subnet.public[1], on main.tf line 30' },
  { level: 'error', text: '✖ Apply failed — 1 error occurred' },
];

export const successExecutionLogs = [
  { level: 'cmd', text: '$ terraform plan -out=tfplan' },
  { level: 'info', text: 'Refreshing state...' },
  { level: 'info', text: 'Plan: 14 to add, 0 to change, 0 to destroy.' },
  { level: 'cmd', text: '$ terraform apply "tfplan"' },
  { level: 'info', text: 'aws_vpc.main: Creating...' },
  { level: 'info', text: 'aws_vpc.main: Creation complete after 2s [id=vpc-0a1b2c3d4e]' },
  { level: 'info', text: 'aws_internet_gateway.main: Creation complete after 1s' },
  { level: 'info', text: 'aws_subnet.public[0]: Creation complete after 1s' },
  { level: 'info', text: 'aws_subnet.public[1]: Creation complete after 1s' },
  { level: 'info', text: 'aws_subnet.private[0]: Creation complete after 1s' },
  { level: 'info', text: 'aws_subnet.private[1]: Creation complete after 1s' },
  { level: 'info', text: 'aws_eip.nat[0]: Creation complete after 1s' },
  { level: 'info', text: 'aws_nat_gateway.main[0]: Creating...' },
  { level: 'info', text: 'aws_nat_gateway.main[0]: Still creating... [30s elapsed]' },
  { level: 'info', text: 'aws_nat_gateway.main[0]: Creation complete after 38s' },
  { level: 'info', text: 'aws_nat_gateway.main[1]: Creation complete after 41s' },
  { level: 'info', text: 'aws_ecs_cluster.main: Creation complete after 3s' },
  { level: 'info', text: 'aws_ecs_service.app: Creation complete after 6s' },
  { level: 'info', text: 'aws_db_instance.postgres: Creating...' },
  { level: 'info', text: 'aws_db_instance.postgres: Still creating... [2m elapsed]' },
  { level: 'info', text: 'aws_db_instance.postgres: Creation complete after 4m12s' },
  { level: 'info', text: 'aws_s3_bucket.assets: Creation complete after 1s' },
  { level: 'success', text: 'Apply complete! Resources: 14 added, 0 changed, 0 destroyed.' },
  { level: 'success', text: 'Outputs: vpc_id, ecs_cluster_name, rds_endpoint, assets_bucket' },
];

export default { failingExecutionLogs, successExecutionLogs };
