/**
 * ContentContainer — page content wrapper (ported from .db-content). Adds the
 * standard padding, a max width for readability, and a fade-in on mount.
 *
 * Props:
 *  - maxWidth: CSS max-width for the inner column (default 1280px)
 */
export default function ContentContainer({ children, maxWidth = 1280 }) {
  return (
    <div className="db-content fade-in">
      <div style={{ maxWidth, margin: '0 auto' }}>{children}</div>
    </div>
  );
}
