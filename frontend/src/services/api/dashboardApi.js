/* ============================================================================
   dashboardApi.js — REAL backend integration for the Dashboard landing page.

   This is the first page migrated off mocks. Unlike the other service modules,
   the Dashboard ALWAYS calls the live FastAPI backend (/api/dashboard/*) — it
   does not honour VITE_USE_MOCK. Each widget has its own endpoint so it can
   load / empty / error / retry independently.

   Backend contract (see backend/app/api/routes/dashboard.py):
     GET /dashboard/metrics          -> { active_projects, running_workflows,
                                          pipeline_success_rate, monthly_cloud_spend }
     GET /dashboard/usage?days=14    -> [{ date, count }]
     GET /dashboard/recent-projects  -> [{ id, name, status, updated_at, ... }]
     GET /dashboard/activity?limit=8 -> [{ id, type, icon, message, at, status }]
   ========================================================================== */
import apiClient from './client';
import { formatCompact } from '@/utils/formatters';

/* ── Presentation config for the 4 KPI tiles ──────────────────────────────
   The backend returns raw numbers; the icon/accent/label/formatting are pure
   presentation and live here so <StatsCard> stays unchanged. */
const STAT_TILES = [
  { id: 'projects',  key: 'active_projects',       label: 'Active Projects',     icon: 'fa-folder-tree',     accent: '#a78bfa', format: 'count',   gradientValue: true },
  { id: 'workflows', key: 'running_workflows',     label: 'Running Workflows',   icon: 'fa-diagram-project', accent: '#60a5fa', format: 'count' },
  { id: 'success',   key: 'pipeline_success_rate', label: 'Pipeline Success',    icon: 'fa-circle-check',    accent: '#34d399', format: 'percent' },
  { id: 'cost',      key: 'monthly_cloud_spend',   label: 'Monthly Cloud Spend', icon: 'fa-coins',           accent: '#fbbf24', format: 'money' },
];

function formatMetric(value, kind) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  const n = Number(value);
  if (kind === 'count') return String(Math.round(n));
  if (kind === 'percent') return `${Math.round(n * 10) / 10}%`;
  if (kind === 'money') return `$${formatCompact(n)}`;
  return String(n);
}

/** Map the backend metrics object into the StatsCard tile array. */
function mapMetrics(data) {
  return STAT_TILES.map((tile) => {
    const metric = data?.[tile.key] || {};
    return {
      id: tile.id,
      label: tile.label,
      value: formatMetric(metric.value, tile.format),
      // Only color/show a delta when the backend actually computed one.
      delta: metric.delta || null,
      trend: metric.trend === 'down' ? 'down' : 'up',
      icon: tile.icon,
      accent: tile.accent,
      gradientValue: !!tile.gradientValue,
    };
  });
}

/** Map the usage series into the {labels, values} shape <AreaChart> expects. */
function mapUsage(points) {
  const list = Array.isArray(points) ? points : [];
  return {
    labels: list.map((p) => shortDay(p.date)),
    values: list.map((p) => Number(p.count) || 0),
  };
}

/** "2026-06-01" -> "Jun 1" (parsed as local midnight to avoid TZ drift). */
function shortDay(isoDate) {
  if (!isoDate) return '';
  const d = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(d.getTime())) return String(isoDate);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/** Map a backend project row into the shape <RecentProjectCard> consumes. */
function mapRecentProject(p) {
  return {
    id: p.id,
    name: p.name,
    description: p.description,
    status: p.status,
    bootstrapStatus: p.bootstrap_status,
    architectureType: p.architecture_type,
    repositoryUrl: p.repository_url,
    monthlyCost: p.monthly_cost,
    updatedAt: p.updated_at,
    createdAt: p.created_at,
  };
}

export const dashboardApi = {
  /** GET /dashboard/metrics -> StatsCard tile array. */
  async getMetrics() {
    const data = await apiClient.get('/dashboard/metrics');
    return mapMetrics(data);
  },

  /** GET /dashboard/usage -> { labels, values } for the area chart. */
  async getUsage(days = 14) {
    const data = await apiClient.get('/dashboard/usage', { params: { days } });
    return mapUsage(data);
  },

  /** GET /dashboard/recent-projects -> mapped project cards. */
  async getRecentProjects(limit = 6) {
    const data = await apiClient.get('/dashboard/recent-projects', { params: { limit } });
    return (Array.isArray(data) ? data : []).map(mapRecentProject);
  },

  /** GET /dashboard/activity -> activity feed items (already feed-shaped). */
  async getActivity(limit = 8) {
    const data = await apiClient.get('/dashboard/activity', { params: { limit } });
    return Array.isArray(data) ? data : [];
  },
};

export default dashboardApi;
