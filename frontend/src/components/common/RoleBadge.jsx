import { getRoleMeta } from '@/utils/constants';

/**
 * RoleBadge — pill showing a member's role (Admin / DevOps Engineer).
 *
 * Props:
 *  - role: "ADMIN" | "DEVOPS_ENGINEER"
 *  - short: use the short label
 */
export default function RoleBadge({ role, short = false }) {
  const meta = getRoleMeta(role);
  return (
    <span
      className="badge-pill"
      style={{
        background: `${meta.color}22`,
        color: meta.color,
      }}
    >
      <i className={`fa-solid ${meta.icon}`} style={{ fontSize: '.7rem' }} />
      {short ? meta.short : meta.label}
    </span>
  );
}
