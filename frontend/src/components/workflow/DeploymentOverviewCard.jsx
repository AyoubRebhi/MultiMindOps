import { formatDate } from '@/utils/formatters';

/**
 * DeploymentOverviewCard — the headline of the Infrastructure Dashboard
 * (Section 1): a success banner plus the deployment overview fields (status,
 * environment, region, workspace, date, duration) and the live endpoint.
 *
 * Props:
 *  - overview: see mockDeploymentOverview
 */
export default function DeploymentOverviewCard({ overview }) {
  if (!overview) return null;

  return (
    <div className="surface depl-overview">
      <div className="depl-banner">
        <span className="depl-banner-ico">
          <i className="fa-solid fa-circle-check" />
        </span>
        <div style={{ minWidth: 0 }}>
          <h2 className="depl-banner-title">{overview.bannerTitle}</h2>
          <p className="depl-banner-sub">{overview.bannerSubtitle}</p>
        </div>
        <span className="badge-pill badge-success depl-banner-badge">
          <i className="fa-solid fa-circle-check" />Deployed
        </span>
      </div>

      <div className="depl-fields">
        <Field icon="fa-circle-check" label="Status" value="Deployed" tone="#34d399" />
        <Field icon="fa-layer-group" label="Environment" value={overview.environment} />
        <Field icon="fa-location-dot" label="Region" value={`${overview.region} · ${overview.regionLabel}`} />
        <Field icon="fa-briefcase" label="Workspace" value={overview.workspace} />
        <Field icon="fa-calendar-check" label="Deployment Date" value={formatDate(overview.deploymentDate)} />
        <Field icon="fa-stopwatch" label="Deployment Duration" value={overview.deploymentDuration} />
      </div>

      {overview.endpoint && (
        <div className="depl-endpoint">
          <i className="fa-solid fa-link me-2" style={{ color: '#60a5fa' }} />
          <span className="depl-endpoint-label">Live endpoint</span>
          <a className="depl-endpoint-url mono" href={overview.endpoint} target="_blank" rel="noreferrer">
            {overview.endpoint}
            <i className="fa-solid fa-arrow-up-right-from-square ms-2" />
          </a>
        </div>
      )}
    </div>
  );
}

function Field({ icon, label, value, tone }) {
  return (
    <div className="depl-field">
      <span className="depl-field-ico">
        <i className={`fa-solid ${icon}`} style={tone ? { color: tone } : undefined} />
      </span>
      <div style={{ minWidth: 0 }}>
        <div className="depl-field-label">{label}</div>
        <div className="depl-field-val">{value}</div>
      </div>
    </div>
  );
}
