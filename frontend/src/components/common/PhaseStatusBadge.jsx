import StatusBadge from './StatusBadge';
import { getPhaseMeta } from '@/utils/constants';

/**
 * PhaseStatusBadge — renders a workflow phase label alongside its status.
 *
 * Props:
 *  - phaseKey: string (e.g. "DOCKER_GENERATION")
 *  - status: string (e.g. "running")
 *  - withLabel: boolean (default false) — prefix the phase name
 */
export default function PhaseStatusBadge({
  phaseKey,
  status,
  withLabel = false,
}) {
  const meta = getPhaseMeta(phaseKey);
  if (!withLabel) return <StatusBadge status={status} />;

  return (
    <span className="d-inline-flex align-items-center gap-2">
      <span style={{ fontSize: '.82rem', color: 'var(--tx2)' }}>
        <i
          className={`${meta.brand ? 'fa-brands' : 'fa-solid'} ${meta.icon} me-1`}
          style={{ color: 'var(--tx3)' }}
        />
        {meta.label}
      </span>
      <StatusBadge status={status} />
    </span>
  );
}
