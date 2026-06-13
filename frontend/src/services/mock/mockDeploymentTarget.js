/* ============================================================================
   mockDeploymentTarget.js — where the pipeline deploys (Section 6 of the
   Execution Center), rendered by <DeploymentTargetCard />. Carries the target
   environment + a four-category architecture summary (networking, compute,
   database, storage). MOCK ONLY.
   ========================================================================== */

export const mockDeploymentTarget = {
  environment: 'Production',
  region: 'eu-west-1',
  regionLabel: 'EU (Ireland)',
  provider: 'AWS',
  workspace: 'Demo Workspace',
  account: '123456789012',
  cluster: 'customer-portal-cluster',

  architecture: [
    {
      key: 'networking',
      title: 'Networking',
      icon: 'fa-network-wired',
      items: [
        '1 VPC (10.0.0.0/16)',
        '4 Subnets (2 public · 2 private)',
        '2 NAT Gateways',
        '1 Application Load Balancer',
      ],
    },
    {
      key: 'compute',
      title: 'Compute',
      icon: 'fa-microchip',
      items: ['1 ECS Cluster (Fargate)', '3 ECS Services', '3 Tasks · 2 vCPU / 4 GB'],
    },
    {
      key: 'database',
      title: 'Database',
      icon: 'fa-database',
      items: ['1 PostgreSQL RDS 16', 'Multi-AZ · db.t3.medium', 'Automated backups (7d)'],
    },
    {
      key: 'storage',
      title: 'Storage',
      icon: 'fa-box-archive',
      items: ['1 S3 Bucket (artifacts)', 'Versioning enabled', 'SSE-S3 encryption'],
    },
  ],
};

export default mockDeploymentTarget;
