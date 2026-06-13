/**
 * DeploymentMetricsCard — the deployment metric cards (Section 5 of the
 * Infrastructure Dashboard): deployment + pipeline duration and the
 * created / updated / failed resource counts.
 *
 * Props:
 *  - metrics: [{ key, icon, label, value, tone }]
 */
export default function DeploymentMetricsCard({ metrics = [] }) {
  return (
    <div className="metric-grid">
      {metrics.map((m) => (
        <div className="metric-tile surface" key={m.key}>
          <span className="metric-tile-ico" style={m.tone ? { color: m.tone, background: `${m.tone}1f` } : undefined}>
            <i className={`fa-solid ${m.icon}`} />
          </span>
          <div className="metric-tile-value">{m.value}</div>
          <div className="metric-tile-label">{m.label}</div>
        </div>
      ))}
    </div>
  );
}
