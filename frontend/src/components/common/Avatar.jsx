import { initials } from '@/utils/formatters';

/**
 * Avatar — circular initials avatar with an optional custom background color.
 *
 * Props:
 *  - name: used to derive initials
 *  - color: background (defaults to the brand gradient)
 *  - size: px (default 32)
 */
export default function Avatar({ name, color, size = 32, className = '', title }) {
  const fontSize = Math.max(10, Math.round(size * 0.4));
  return (
    <span
      className={`av ${className}`.trim()}
      title={title || name}
      style={{
        width: size,
        height: size,
        fontSize,
        background: color || undefined,
      }}
    >
      {initials(name)}
    </span>
  );
}
