/* ============================================================================
   mockTerraformResources.js — the resources the generated configuration would
   create, grouped for the Review & Approval summary and the final deployment
   result. MOCK ONLY.
   ========================================================================== */

export const mockTerraformResources = [
  {
    group: 'Networking',
    icon: 'fa-network-wired',
    accent: '#60a5fa',
    items: [
      { name: 'VPC', count: 1, icon: 'fa-cloud', resource: 'aws_vpc' },
      { name: 'Subnets', count: 4, icon: 'fa-diagram-project', resource: 'aws_subnet' },
      { name: 'NAT Gateways', count: 2, icon: 'fa-shuffle', resource: 'aws_nat_gateway' },
      { name: 'Internet Gateway', count: 1, icon: 'fa-globe', resource: 'aws_internet_gateway' },
    ],
  },
  {
    group: 'Compute',
    icon: 'fa-server',
    accent: '#a78bfa',
    items: [
      { name: 'ECS Cluster', count: 1, icon: 'fa-server', resource: 'aws_ecs_cluster' },
      { name: 'ECS Service', count: 1, icon: 'fa-cubes', resource: 'aws_ecs_service' },
    ],
  },
  {
    group: 'Database',
    icon: 'fa-database',
    accent: '#34d399',
    items: [
      { name: 'PostgreSQL RDS', count: 1, icon: 'fa-database', resource: 'aws_db_instance' },
    ],
  },
  {
    group: 'Storage',
    icon: 'fa-hard-drive',
    accent: '#fbbf24',
    items: [
      { name: 'S3 Bucket', count: 1, icon: 'fa-bucket', resource: 'aws_s3_bucket' },
    ],
  },
];

/** Total resource count across all groups (used as "Resources Created"). */
export const totalResourceCount = mockTerraformResources.reduce(
  (sum, g) => sum + g.items.reduce((s, i) => s + i.count, 0),
  0
);

export default mockTerraformResources;
