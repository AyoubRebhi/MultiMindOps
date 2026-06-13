/* ============================================================================
   mockInfrastructureResources.js — the deployed infrastructure shown on the
   Infrastructure Dashboard (Phase 7). `summary` drives the category roll-up
   (Section 2) and `inventory` drives the searchable/sortable
   <ResourceInventoryTable /> (Section 3). MOCK ONLY — no cloud resources exist.
   ========================================================================== */

export const infrastructureSummary = [
  {
    key: 'networking',
    title: 'Networking',
    icon: 'fa-network-wired',
    items: [
      { label: '1 VPC', ok: true },
      { label: '4 Subnets', ok: true },
      { label: '2 NAT Gateways', ok: true },
      { label: '1 Load Balancer', ok: true },
    ],
  },
  {
    key: 'compute',
    title: 'Compute',
    icon: 'fa-microchip',
    items: [
      { label: '1 ECS Cluster', ok: true },
      { label: '3 ECS Services', ok: true },
    ],
  },
  {
    key: 'database',
    title: 'Database',
    icon: 'fa-database',
    items: [{ label: '1 PostgreSQL RDS', ok: true }],
  },
  {
    key: 'storage',
    title: 'Storage',
    icon: 'fa-box-archive',
    items: [{ label: '1 S3 Bucket', ok: true }],
  },
];

export const infrastructureInventory = [
  { name: 'customer-portal-vpc', type: 'aws_vpc', category: 'Networking', status: 'active', region: 'eu-west-1', createdAt: '2026-06-13T08:06:02Z' },
  { name: 'public-subnet-1a', type: 'aws_subnet', category: 'Networking', status: 'active', region: 'eu-west-1a', createdAt: '2026-06-13T08:06:05Z' },
  { name: 'public-subnet-1b', type: 'aws_subnet', category: 'Networking', status: 'active', region: 'eu-west-1b', createdAt: '2026-06-13T08:06:05Z' },
  { name: 'private-subnet-1a', type: 'aws_subnet', category: 'Networking', status: 'active', region: 'eu-west-1a', createdAt: '2026-06-13T08:06:06Z' },
  { name: 'private-subnet-1b', type: 'aws_subnet', category: 'Networking', status: 'active', region: 'eu-west-1b', createdAt: '2026-06-13T08:06:06Z' },
  { name: 'nat-gateway-1a', type: 'aws_nat_gateway', category: 'Networking', status: 'active', region: 'eu-west-1a', createdAt: '2026-06-13T08:06:21Z' },
  { name: 'nat-gateway-1b', type: 'aws_nat_gateway', category: 'Networking', status: 'active', region: 'eu-west-1b', createdAt: '2026-06-13T08:06:21Z' },
  { name: 'customer-portal-alb', type: 'aws_lb', category: 'Networking', status: 'active', region: 'eu-west-1', createdAt: '2026-06-13T08:06:34Z' },
  { name: 'customer-portal-cluster', type: 'aws_ecs_cluster', category: 'Compute', status: 'active', region: 'eu-west-1', createdAt: '2026-06-13T08:06:40Z' },
  { name: 'customer-portal-service', type: 'aws_ecs_service', category: 'Compute', status: 'active', region: 'eu-west-1', createdAt: '2026-06-13T08:06:58Z' },
  { name: 'worker-service', type: 'aws_ecs_service', category: 'Compute', status: 'active', region: 'eu-west-1', createdAt: '2026-06-13T08:06:59Z' },
  { name: 'scheduler-service', type: 'aws_ecs_service', category: 'Compute', status: 'active', region: 'eu-west-1', createdAt: '2026-06-13T08:07:00Z' },
  { name: 'customer-portal-db', type: 'aws_db_instance', category: 'Database', status: 'active', region: 'eu-west-1', createdAt: '2026-06-13T08:06:48Z' },
  { name: 'customer-portal-artifacts', type: 'aws_s3_bucket', category: 'Storage', status: 'active', region: 'eu-west-1', createdAt: '2026-06-13T08:06:12Z' },
];

export default { infrastructureSummary, infrastructureInventory };
