/* ============================================================================
   mockPlans.js — Planning Agent output for the demo project: a requirements
   summary plus three side-by-side architecture plans (Low Cost / Balanced /
   High Performance). The Balanced plan is flagged as recommended.
   ========================================================================== */

/** Section 1 of the Planning page — the Planning Agent's reasoning result. */
export const mockPlanningResult = {
  projectId: 'prj-002',
  requirementsSummary:
    'A customer-facing web portal (React SPA + Node BFF) expecting bursty daytime traffic, session affinity via Redis, and the need for zero-downtime deploys. Stateless application tier; state lives in managed Redis and an external database.',
  complexity: {
    level: 'Moderate',
    score: 58, // 0–100
    drivers: ['Two runtime services', 'Session/cache dependency', 'Public-facing TLS + CDN'],
  },
  infrastructureSize: {
    label: 'Small–Medium',
    detail: '2 containers · 1 managed cache · 1 load balancer',
    icon: 'fa-server',
  },
  teamScale: {
    label: '1–3 engineers',
    detail: 'Low operational overhead; suits a small DevOps team.',
    icon: 'fa-users',
  },
  trafficProfile: {
    label: 'Bursty (business hours)',
    detail: '~2k req/min peak, near-idle overnight',
    icon: 'fa-chart-line',
  },
};

/** Section 2 — the three candidate plans rendered as PlanSelectionCards. */
export const mockPlans = [
  {
    id: 'plan-low',
    tier: 'low',
    name: 'Low Cost',
    tagline: 'Minimal footprint for small workloads',
    recommended: false,
    monthlyCost: 96,
    scalability: { label: 'Limited', level: 1 },
    availability: { label: 'Single-AZ', level: 1 },
    awsServices: [
      { name: 'EC2 (t3.small)', icon: 'fa-server' },
      { name: 'Elastic IP', icon: 'fa-network-wired' },
      { name: 'ElastiCache (t3.micro)', icon: 'fa-database' },
      { name: 'S3 + CloudFront', icon: 'fa-globe' },
    ],
    characteristics: [
      'Lowest monthly cost',
      'Single instance, manual scaling',
      'Best for demos & small workloads',
    ],
    tradeoffs: {
      pros: ['Cheapest option', 'Simple to operate', 'Fast to provision'],
      cons: ['No high availability', 'Manual scaling only', 'Downtime during deploys'],
    },
  },
  {
    id: 'plan-balanced',
    tier: 'balanced',
    name: 'Balanced',
    tagline: 'Cost/performance balance for production',
    recommended: true,
    monthlyCost: 268,
    scalability: { label: 'Moderate', level: 2 },
    availability: { label: 'Multi-AZ', level: 2 },
    awsServices: [
      { name: 'ECS Fargate (2 tasks)', icon: 'fa-server' },
      { name: 'Application Load Balancer', icon: 'fa-network-wired' },
      { name: 'ElastiCache Redis (Multi-AZ)', icon: 'fa-database' },
      { name: 'S3 + CloudFront', icon: 'fa-globe' },
    ],
    characteristics: [
      'Recommended for most teams',
      'Auto-scaling across 2 AZs',
      'Zero-downtime rolling deploys',
    ],
    tradeoffs: {
      pros: ['Highly available', 'Autoscaling', 'No server management'],
      cons: ['Higher cost than single EC2', 'Per-task billing at scale'],
    },
  },
  {
    id: 'plan-high',
    tier: 'high',
    name: 'High Performance',
    tagline: 'Maximum availability & scale',
    recommended: false,
    monthlyCost: 642,
    scalability: { label: 'High', level: 3 },
    availability: { label: 'Multi-AZ (3) + auto-heal', level: 3 },
    awsServices: [
      { name: 'EKS (3 nodes, 3 AZ)', icon: 'fa-dharmachakra' },
      { name: 'Application Load Balancer', icon: 'fa-network-wired' },
      { name: 'ElastiCache Cluster', icon: 'fa-database' },
      { name: 'CloudFront + WAF', icon: 'fa-shield-halved' },
    ],
    characteristics: [
      'Highest availability & throughput',
      'Kubernetes-native autoscaling',
      'For large, latency-sensitive traffic',
    ],
    tradeoffs: {
      pros: ['Maximum scale & resilience', 'Fine-grained control', 'Self-healing'],
      cons: ['Highest cost', 'Cluster ops overhead', 'Overkill for small loads'],
    },
  },
];

export default mockPlans;
