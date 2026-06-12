/* ============================================================================
   mockArchitecturePlans.js — candidate architectures proposed per project,
   with comparison options the user would later approve.
   ========================================================================== */

export const mockArchitecturePlans = [
  {
    id: 'arch-001',
    projectId: 'prj-001',
    projectName: 'Payments API',
    title: 'Containerized API on ECS Fargate',
    provider: 'aws',
    status: 'approved',
    summary:
      'Serverless containers behind an ALB with a managed PostgreSQL database and private networking. Chosen for low ops overhead and elastic scaling.',
    estimatedCost: 412,
    components: [
      { name: 'ECS Fargate', type: 'compute', icon: 'fa-server' },
      { name: 'Application Load Balancer', type: 'networking', icon: 'fa-network-wired' },
      { name: 'RDS PostgreSQL', type: 'database', icon: 'fa-database' },
      { name: 'VPC + Private Subnets', type: 'networking', icon: 'fa-shield-halved' },
    ],
    options: [
      {
        name: 'ECS Fargate',
        recommended: true,
        monthlyCost: 412,
        pros: ['No server management', 'Fast autoscaling', 'Per-second billing'],
        cons: ['Higher unit cost at scale'],
      },
      {
        name: 'EKS (Kubernetes)',
        recommended: false,
        monthlyCost: 690,
        pros: ['Portable workloads', 'Fine-grained control'],
        cons: ['Control-plane cost', 'More operational overhead'],
      },
      {
        name: 'EC2 Auto Scaling',
        recommended: false,
        monthlyCost: 305,
        pros: ['Cheapest at steady load', 'Full host access'],
        cons: ['Patching & AMI ops', 'Slower to scale'],
      },
    ],
  },
  {
    id: 'arch-002',
    projectId: 'prj-002',
    projectName: 'Customer Portal',
    title: 'Static SPA + BFF behind CloudFront',
    provider: 'aws',
    status: 'awaiting_approval',
    summary:
      'React SPA served from S3/CloudFront with a small Node BFF on Fargate, backed by Redis for sessions. Cost-optimized for spiky traffic.',
    estimatedCost: 268,
    components: [
      { name: 'CloudFront + S3', type: 'cdn', icon: 'fa-globe' },
      { name: 'Fargate BFF', type: 'compute', icon: 'fa-server' },
      { name: 'ElastiCache Redis', type: 'cache', icon: 'fa-bolt' },
    ],
    options: [
      {
        name: 'CloudFront + Fargate BFF',
        recommended: true,
        monthlyCost: 268,
        pros: ['Cheap static delivery', 'Edge caching', 'Scales to zero-ish'],
        cons: ['Two deploy targets'],
      },
      {
        name: 'Amplify Hosting',
        recommended: false,
        monthlyCost: 240,
        pros: ['Fully managed CI/CD', 'Simple setup'],
        cons: ['Less control', 'Vendor lock-in'],
      },
    ],
  },
  {
    id: 'arch-003',
    projectId: 'prj-003',
    projectName: 'Data Pipeline',
    title: 'Spark on GKE with autoscaling node pools',
    provider: 'gcp',
    status: 'approved',
    summary:
      'Kubernetes-native Spark workload with a dedicated autoscaling node pool and Kafka ingestion. Helm-packaged for repeatable deploys.',
    estimatedCost: 936,
    components: [
      { name: 'GKE Cluster', type: 'compute', icon: 'fa-dharmachakra' },
      { name: 'Kafka (Confluent)', type: 'streaming', icon: 'fa-wave-square' },
      { name: 'Cloud Storage', type: 'storage', icon: 'fa-hard-drive' },
      { name: 'BigQuery', type: 'analytics', icon: 'fa-chart-column' },
    ],
    options: [
      {
        name: 'GKE Autopilot',
        recommended: true,
        monthlyCost: 936,
        pros: ['Per-pod billing', 'Managed nodes', 'Good for bursty batch'],
        cons: ['Less node-level tuning'],
      },
      {
        name: 'Dataproc',
        recommended: false,
        monthlyCost: 1120,
        pros: ['Purpose-built for Spark', 'Ephemeral clusters'],
        cons: ['Pricier', 'Less general-purpose'],
      },
    ],
  },
  {
    id: 'arch-004',
    projectId: 'prj-004',
    projectName: 'Auth Service',
    title: 'OIDC service on AKS',
    provider: 'azure',
    status: 'draft',
    summary:
      'Spring Boot OIDC service on AKS with an Azure Database for PostgreSQL. Draft pending container build remediation.',
    estimatedCost: 184,
    components: [
      { name: 'AKS Cluster', type: 'compute', icon: 'fa-dharmachakra' },
      { name: 'Azure DB for PostgreSQL', type: 'database', icon: 'fa-database' },
      { name: 'Key Vault', type: 'security', icon: 'fa-key' },
    ],
    options: [
      {
        name: 'AKS',
        recommended: true,
        monthlyCost: 184,
        pros: ['Native to Azure estate', 'Workload identity'],
        cons: ['Cluster ops overhead'],
      },
      {
        name: 'Container Apps',
        recommended: false,
        monthlyCost: 156,
        pros: ['Serverless scale', 'Simpler ops'],
        cons: ['Fewer networking knobs'],
      },
    ],
  },
];
