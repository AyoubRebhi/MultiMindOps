/**
 * DeploymentTargetCard — where the pipeline deploys (Section 6 of the Execution
 * Center). Top row: environment, region, cloud provider and workspace. Below: a
 * four-category architecture summary (networking, compute, database, storage).
 *
 * Props:
 *  - target: see mockDeploymentTarget
 */
export default function DeploymentTargetCard({ target }) {
  if (!target) return null;

  return (
    <div className="dt-card">
      <div className="dt-top">
        <DtField icon="fa-layer-group" label="Environment" value={target.environment} tone="prod" />
        <DtField icon="fa-location-dot" label="Region" value={`${target.region}${target.regionLabel ? ` · ${target.regionLabel}` : ''}`} />
        <DtField icon="fa-aws" brand label="Cloud Provider" value={target.provider} />
        <DtField icon="fa-briefcase" label="Workspace" value={target.workspace} />
        <DtField icon="fa-id-card-clip" label="AWS Account" value={target.account} mono />
        <DtField icon="fa-layer-group" label="Cluster" value={target.cluster} mono />
      </div>

      <div className="reasoning-label mt-3 mb-2">
        <i className="fa-solid fa-sitemap me-2" style={{ color: '#a78bfa' }} />
        Architecture Summary
      </div>
      <div className="dt-arch">
        {target.architecture.map((cat) => (
          <div className="dt-arch-cat" key={cat.key}>
            <div className="dt-arch-head">
              <span className="dt-arch-ico"><i className={`fa-solid ${cat.icon}`} /></span>
              {cat.title}
            </div>
            <ul className="dt-arch-list">
              {cat.items.map((it) => (
                <li key={it}>
                  <i className="fa-solid fa-circle-check" />
                  <span>{it}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function DtField({ icon, brand = false, label, value, mono = false, tone }) {
  return (
    <div className="dt-field">
      <span className={`dt-field-ico ${tone ? `dt-field-ico-${tone}` : ''}`.trim()}>
        <i className={`${brand ? 'fa-brands' : 'fa-solid'} ${icon}`} />
      </span>
      <div style={{ minWidth: 0 }}>
        <div className="dt-field-label">{label}</div>
        <div className={`dt-field-val ${mono ? 'mono' : ''}`.trim()}>{value}</div>
      </div>
    </div>
  );
}
