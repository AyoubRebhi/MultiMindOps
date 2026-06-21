import TerraformResourceSummary from '@/components/workflow/TerraformResourceSummary';

/**
 * TerraformInfrastructureSummary — the human-readable "what will be created"
 * card derived from a successful `terraform plan`. It consumes the backend's
 * categorized Infrastructure Summary (normalized via
 * `normalizeInfrastructureSummary` → { totalResources, categories:[{ name,
 * items:[{ type, label, count }] }] }) and renders it with the SAME
 * `TerraformResourceSummary` card primitive used elsewhere, so the look matches
 * the Architecture Summary UI. Read-only; every count comes straight from the
 * plan — nothing is synthesized.
 *
 * The categories already cover the dimensions the phase spec calls for —
 * Compute · Networking · Storage · Database · Security (+ Other) — because the
 * backend catalog buckets every resource type into exactly those groups.
 *
 * @param {{ summary: { totalResources: number,
 *   categories: Array<{ name: string,
 *     items: Array<{ type: string, label: string, count: number }> }> } }} props
 */

// Per-category icon + accent. Matches the backend _CATEGORY_ORDER (plan_summary.py).
const CATEGORY_META = {
  Networking: { icon: 'fa-network-wired', accent: '#60a5fa' },
  Compute: { icon: 'fa-microchip', accent: '#34d399' },
  Database: { icon: 'fa-database', accent: '#a78bfa' },
  Storage: { icon: 'fa-box-archive', accent: '#fbbf24' },
  Security: { icon: 'fa-shield-halved', accent: '#f87171' },
  Other: { icon: 'fa-cube', accent: 'var(--tx3)' },
};

/** Map normalized categories → the TerraformResourceSummary `resources` shape. */
function toResourceGroups(categories) {
  return (categories || []).map((c) => {
    const meta = CATEGORY_META[c.name] || CATEGORY_META.Other;
    return {
      group: c.name,
      icon: meta.icon,
      accent: meta.accent,
      items: (c.items || []).map((i) => ({
        name: i.label,
        count: i.count,
        icon: meta.icon,
      })),
    };
  });
}

export default function TerraformInfrastructureSummary({ summary }) {
  if (!summary || !Array.isArray(summary.categories) || summary.categories.length === 0) {
    return null;
  }
  const groups = toResourceGroups(summary.categories);
  const total = summary.totalResources ?? 0;

  return (
    <div className="surface">
      <div className="d-flex align-items-center gap-2 flex-wrap mb-3">
        <span className="section-label-chip">
          <i className="fa-solid fa-diagram-project" />
        </span>
        <span style={{ fontSize: '.9rem', fontWeight: 600 }}>Infrastructure Summary</span>
        <span
          className="badge-pill"
          style={{
            background: 'rgba(52,211,153,.12)',
            color: '#34d399',
            fontWeight: 600,
            fontSize: '.74rem',
          }}
        >
          <i className="fa-solid fa-cubes-stacked me-2" />
          {total} resource{total === 1 ? '' : 's'} to create
        </span>
        <span className="text-muted-3" style={{ fontSize: '.74rem' }}>
          {groups.length} categor{groups.length === 1 ? 'y' : 'ies'}
        </span>
      </div>
      <TerraformResourceSummary resources={groups} checked />
    </div>
  );
}
