/* ============================================================================
   analysisHelpers.js — non-component helpers shared by the Workflow Analysis
   panels. Kept separate from AnalysisPanelBits.jsx so that file exports only
   components (satisfies react-refresh/only-export-components).
   ========================================================================== */

/** Severity → badge variant (matches the platform's STATUS/badge palette). */
export const SEV_VARIANT = { critical: 'danger', high: 'danger', medium: 'warning', low: 'info' };

/** Score ring color by 0–100 band. */
export function scoreColor(score) {
  if (score >= 80) return '#34d399';
  if (score >= 60) return '#fbbf24';
  return '#f87171';
}
