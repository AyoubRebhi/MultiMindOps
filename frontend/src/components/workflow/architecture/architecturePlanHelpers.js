/* ============================================================================
   architecturePlanHelpers.js — pure (non-component) helpers shared by the
   Architecture Planning card + comparison table. Kept in a plain .js module so
   the .jsx component files only export components (react-refresh friendly).

   These never invent data — they only format/scale what the backend returned.
   ========================================================================== */
import { titleize } from '@/utils/formatters';

/** Per-strategy icon (matches the backend plan ids). */
export const PLAN_ICON = {
  low_cost: 'fa-piggy-bank',
  balanced: 'fa-scale-balanced',
  high_performance: 'fa-gauge-high',
};

export function planIcon(id) {
  return PLAN_ICON[id] || 'fa-sitemap';
}

/** Map a scalability tier (Low/Medium/High) to a 1–3 dot level. */
export function scalabilityLevel(tier) {
  const t = String(tier || '').toLowerCase();
  if (t.includes('high')) return 3;
  if (t.includes('medium')) return 2;
  if (t.includes('low')) return 1;
  return 0;
}

/** Map an availability level string to a 1–3 dot level. */
export function availabilityLevel(level) {
  const t = String(level || '').toLowerCase();
  if (t.includes('replica')) return 3; // "Multi-AZ + Read Replicas"
  if (t.includes('multi')) return 2; // "Multi-AZ"
  if (t.includes('single')) return 1; // "Single-AZ"
  return 0;
}

/** Operational complexity → badge metadata (lower is greener). */
export function complexityMeta(complexity) {
  const c = String(complexity || '').toLowerCase();
  if (c === 'low') return { label: 'Low', variant: 'success' };
  if (c === 'high') return { label: 'High', variant: 'warning' };
  if (c === 'medium') return { label: 'Medium', variant: 'info' };
  return { label: complexity || '—', variant: 'pending' };
}

/** Human label for the cost profile (e.g. "cost_optimized" → "Cost Optimized"). */
export function costProfileLabel(profile) {
  return profile ? titleize(profile) : null;
}

/** Title-cased architecture pattern (e.g. "microservices" → "Microservices"). */
export function patternLabel(style) {
  return style ? titleize(style) : '—';
}
