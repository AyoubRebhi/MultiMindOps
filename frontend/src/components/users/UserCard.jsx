import Avatar from '@/components/common/Avatar';
import RoleBadge from '@/components/common/RoleBadge';
import StatusBadge from '@/components/common/StatusBadge';
import { formatDate } from '@/utils/formatters';

/**
 * UserCard — compact member card (avatar, identity, role, status).
 *
 * Props:
 *  - user: see mockUsers shape
 *  - actions: optional node (e.g. an actions menu) rendered top-right
 */
export default function UserCard({ user, actions }) {
  if (!user) return null;
  const { name, email, role, status, joinedDate, projects } = user;

  return (
    <div className="surface surface-hover h-100">
      <div className="d-flex align-items-start justify-content-between mb-3">
        <div className="d-flex align-items-center gap-3">
          <Avatar name={name} color={user.avatarColor} size={44} />
          <div>
            <div style={{ fontWeight: 600 }}>{name}</div>
            <div style={{ fontSize: '.78rem', color: 'var(--tx3)' }}>{email}</div>
          </div>
        </div>
        {actions}
      </div>

      <div className="d-flex flex-wrap align-items-center gap-2 mb-3">
        <RoleBadge role={role} />
        <StatusBadge status={status} />
      </div>

      <div
        className="d-flex align-items-center justify-content-between pt-3"
        style={{ borderTop: '1px solid var(--bd)', fontSize: '.74rem', color: 'var(--tx3)' }}
      >
        <span>
          <i className="fa-solid fa-folder me-1" />
          {projects} {projects === 1 ? 'project' : 'projects'}
        </span>
        <span>
          <i className="fa-regular fa-calendar me-1" />
          {joinedDate ? `Joined ${formatDate(joinedDate)}` : 'Not joined yet'}
        </span>
      </div>
    </div>
  );
}
