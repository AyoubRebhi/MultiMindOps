/* ============================================================================
   formatters.js — small, dependency-free presentation helpers.
   ========================================================================== */

/** Format an ISO date string as e.g. "Jun 12, 2026". */
export function formatDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

/** Relative "time ago" string from an ISO date (e.g. "3h ago"). */
export function timeAgo(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const seconds = Math.floor((Date.now() - d.getTime()) / 1000);
  if (seconds < 60) return 'just now';
  const steps = [
    ['y', 31536000],
    ['mo', 2592000],
    ['d', 86400],
    ['h', 3600],
    ['m', 60],
  ];
  for (const [label, secs] of steps) {
    const n = Math.floor(seconds / secs);
    if (n >= 1) return `${n}${label} ago`;
  }
  return 'just now';
}

/** Format a number as USD currency (no decimals by default). */
export function formatCurrency(amount, { decimals = 0 } = {}) {
  if (amount == null || Number.isNaN(Number(amount))) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(Number(amount));
}

/** Compact number formatting: 24800 -> "24.8K". */
export function formatCompact(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return new Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(Number(value));
}

/** Clamp a 0–100 percentage and round it. */
export function clampPercent(value) {
  const n = Number(value) || 0;
  return Math.max(0, Math.min(100, Math.round(n)));
}

/** Turn "REPO_ANALYSIS" / "human_review" into "Repo Analysis" / "Human Review". */
export function titleize(value) {
  if (!value) return '';
  return String(value)
    .toLowerCase()
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** First letters of a name, e.g. "Ayoub Rebhi" -> "AR". */
export function initials(name) {
  if (!name) return '?';
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() || '')
    .join('');
}
