/* ============================================================================
   mockDeploymentMetrics.js — headline metrics for the Infrastructure Dashboard
   (Section 5), rendered as metric cards by <DeploymentMetricsCard />.
   MOCK ONLY.
   ========================================================================== */

export const mockDeploymentMetrics = [
  { key: 'deployDuration', icon: 'fa-stopwatch', label: 'Deployment Duration', value: '1m 23s', tone: '#60a5fa' },
  { key: 'pipelineDuration', icon: 'fa-gauge-high', label: 'Pipeline Duration', value: '3m 01s', tone: '#a78bfa' },
  { key: 'created', icon: 'fa-circle-plus', label: 'Resources Created', value: 23, tone: '#34d399' },
  { key: 'updated', icon: 'fa-pen-to-square', label: 'Resources Updated', value: 0, tone: '#fbbf24' },
  { key: 'failed', icon: 'fa-circle-xmark', label: 'Resources Failed', value: 0, tone: '#f87171' },
];

export default mockDeploymentMetrics;
