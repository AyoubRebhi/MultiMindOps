/* ============================================================================
   mockInfrastructureTopology.js — the deployed architecture for the
   Infrastructure Dashboard (Section 4), drawn with plain cards + connectors by
   <InfrastructureTopology /> (no external diagram libraries). A vertical flow
   from the public internet down to the database, with the `via` label shown on
   the connector to the next tier. MOCK ONLY.
   ========================================================================== */

export const mockInfrastructureTopology = {
  region: 'eu-west-1',
  flow: [
    {
      key: 'users',
      label: 'Users / Clients',
      detail: 'Public internet · HTTPS',
      icon: 'fa-users',
      tone: 'neutral',
      via: 'HTTPS :443',
    },
    {
      key: 'alb',
      label: 'Application Load Balancer',
      detail: 'customer-portal-alb · 2 AZs',
      icon: 'fa-network-wired',
      tone: 'blue',
      via: 'forwards',
    },
    {
      key: 'ecs',
      label: 'ECS Fargate Cluster',
      detail: 'customer-portal-cluster · 3 services',
      icon: 'fa-layer-group',
      tone: 'purple',
      via: 'runs',
    },
    {
      key: 'app',
      label: 'Application Containers',
      detail: '3 tasks · 2 vCPU / 4 GB · :8080',
      icon: 'fa-docker',
      brand: true,
      tone: 'cyan',
      via: 'queries',
    },
    {
      key: 'rds',
      label: 'PostgreSQL RDS',
      detail: 'customer-portal-db · Multi-AZ · db.t3.medium',
      icon: 'fa-database',
      tone: 'green',
      via: null,
    },
  ],
  // Side resources attached to the compute tier (rendered as a small aside).
  attached: [
    { key: 's3', label: 'S3 Artifacts Bucket', detail: 'customer-portal-artifacts', icon: 'fa-box-archive' },
    { key: 'ecr', label: 'Amazon ECR', detail: 'customer-portal-api:a1b2c3d', icon: 'fa-box' },
  ],
};

export default mockInfrastructureTopology;
