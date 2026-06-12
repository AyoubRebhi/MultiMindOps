/**
 * StatsCard — KPI tile (ported from the template's .db-stat-card).
 *
 * Props:
 *  - label, value: the metric
 *  - delta: optional change text (e.g. "+18.4%")
 *  - trend: "up" | "down" — colors the delta
 *  - icon: Font Awesome class (e.g. "fa-folder-tree")
 *  - accent: icon color (CSS color)
 *  - gradientValue: render the value with the brand gradient text
 */
export default function StatsCard({
  label,
  value,
  delta,
  trend = 'up',
  icon = 'fa-chart-simple',
  accent = '#a78bfa',
  gradientValue = false,
}) {
  return (
    <div className="db-stat-card">
      <div className="d-flex justify-content-between align-items-start mb-3">
        <div
          className="icon-tile"
          style={{ background: hexToSoft(accent), color: accent }}
        >
          <i className={`fa-solid ${icon}`} />
        </div>
        {delta && (
          <span
            className={`badge-pill ${
              trend === 'down' ? 'badge-danger' : 'badge-success'
            }`}
          >
            <i
              className={`fa-solid ${
                trend === 'down' ? 'fa-arrow-down' : 'fa-arrow-up'
              }`}
              style={{ fontSize: '.62rem' }}
            />
            {delta}
          </span>
        )}
      </div>
      <div className={`db-stat-val ${gradientValue ? 'gt' : ''}`.trim()}>
        {value}
      </div>
      <div className="db-stat-lbl">{label}</div>
    </div>
  );
}

/** Build a translucent background from a hex accent color. */
function hexToSoft(hex, alpha = 0.15) {
  const m = hex.replace('#', '');
  const r = parseInt(m.slice(0, 2), 16);
  const g = parseInt(m.slice(2, 4), 16);
  const b = parseInt(m.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
