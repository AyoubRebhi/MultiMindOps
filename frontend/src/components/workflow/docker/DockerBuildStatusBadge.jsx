/**
 * DockerBuildStatusBadge — renders the build state straight from the BACKEND
 * (`GET /execution/docker/status` / the WS `complete` event). It NEVER infers
 * status from log text. Statuses map: pending→Queued, running→Running,
 * success→Succeeded, failed→Failed, blocked→Blocked.
 *
 * Props:
 *  - status   backend build status string
 */
const STATUS_MAP = {
  pending: { label: 'Queued', variant: 'pending', icon: 'fa-clock', spin: false },
  queued: { label: 'Queued', variant: 'pending', icon: 'fa-clock', spin: false },
  running: { label: 'Running', variant: 'running', icon: 'fa-spinner', spin: true },
  success: { label: 'Succeeded', variant: 'success', icon: 'fa-circle-check', spin: false },
  succeeded: { label: 'Succeeded', variant: 'success', icon: 'fa-circle-check', spin: false },
  failed: { label: 'Failed', variant: 'danger', icon: 'fa-circle-xmark', spin: false },
  blocked: { label: 'Blocked', variant: 'danger', icon: 'fa-ban', spin: false },
};

export default function DockerBuildStatusBadge({ status }) {
  const meta = STATUS_MAP[String(status || '').toLowerCase()] || STATUS_MAP.pending;
  return (
    <span className={`badge-pill badge-${meta.variant}`} style={{ fontSize: '.72rem' }}>
      <i className={`fa-solid ${meta.icon}${meta.spin ? ' fa-spin' : ''}`} />
      {meta.label}
    </span>
  );
}
