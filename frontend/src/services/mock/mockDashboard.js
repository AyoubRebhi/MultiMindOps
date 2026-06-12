/* ============================================================================
   mockDashboard.js — headline stats, the deployments trend, and a live
   activity feed for the Dashboard landing page.
   ========================================================================== */

export const mockDashboardStats = [
  {
    id: 'projects',
    label: 'Active Projects',
    value: 6,
    delta: '+2 this month',
    trend: 'up',
    icon: 'fa-folder-tree',
    accent: '#a78bfa',
  },
  {
    id: 'workflows',
    label: 'Workflow Runs',
    value: 128,
    delta: '+18.4%',
    trend: 'up',
    icon: 'fa-diagram-project',
    accent: '#60a5fa',
  },
  {
    id: 'success',
    label: 'Pipeline Success',
    value: '94.2%',
    delta: '+3.1%',
    trend: 'up',
    icon: 'fa-circle-check',
    accent: '#34d399',
  },
  {
    id: 'cost',
    label: 'Monthly Cloud Spend',
    value: '$1.8K',
    delta: '-6.2%',
    trend: 'down',
    icon: 'fa-coins',
    accent: '#fbbf24',
  },
];

/** Last 14 days of completed workflow runs (used by the trend chart). */
export const mockDeploymentsTrend = {
  labels: [
    'May 30', 'May 31', 'Jun 1', 'Jun 2', 'Jun 3', 'Jun 4', 'Jun 5',
    'Jun 6', 'Jun 7', 'Jun 8', 'Jun 9', 'Jun 10', 'Jun 11', 'Jun 12',
  ],
  values: [4, 6, 5, 9, 7, 8, 11, 9, 12, 10, 13, 11, 15, 14],
};

export const mockActivityFeed = [
  {
    id: 'act-1',
    type: 'success',
    icon: 'fa-circle-check',
    message: 'Payments API deployed to production (eu-west-1)',
    at: '2026-06-11T14:05:00Z',
  },
  {
    id: 'act-2',
    type: 'running',
    icon: 'fa-spinner',
    message: 'Customer Portal — Terraform provisioning started',
    at: '2026-06-12T08:42:00Z',
  },
  {
    id: 'act-3',
    type: 'warning',
    icon: 'fa-user-check',
    message: 'Auth Service container build needs human review',
    at: '2026-06-12T07:55:00Z',
  },
  {
    id: 'act-4',
    type: 'info',
    icon: 'fa-wand-magic-sparkles',
    message: 'AI corrector proposed a fix for missing non-root USER',
    at: '2026-06-12T07:48:00Z',
  },
  {
    id: 'act-5',
    type: 'danger',
    icon: 'fa-triangle-exclamation',
    message: 'Data Pipeline reporting degraded GKE node pool',
    at: '2026-06-10T19:18:00Z',
  },
];
