import Avatar from './Avatar';

/**
 * MemberAvatarGroup — overlapping avatar stack with a "+N" overflow chip.
 *
 * Props:
 *  - members: [{ name, avatarColor }]
 *  - max: how many avatars to show before collapsing (default 5)
 *  - size: px (default 32)
 */
export default function MemberAvatarGroup({ members = [], max = 5, size = 32 }) {
  const shown = members.slice(0, max);
  const overflow = members.length - shown.length;
  const fontSize = Math.max(10, Math.round(size * 0.36));

  return (
    <div className="avatar-group">
      {shown.map((m, i) => (
        <Avatar key={m.id || m.email || i} name={m.name} color={m.avatarColor} size={size} />
      ))}
      {overflow > 0 && (
        <span
          className="av av-more"
          style={{ width: size, height: size, fontSize }}
          title={`${overflow} more`}
        >
          +{overflow}
        </span>
      )}
    </div>
  );
}
