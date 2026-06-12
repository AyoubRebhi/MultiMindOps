/**
 * EmptyState — friendly placeholder for empty lists / no-data views.
 *
 * Props:
 *  - icon: Font Awesome class (default fa-inbox)
 *  - title, message: copy
 *  - action: optional node (e.g. a CTA button)
 */
export default function EmptyState({
  icon = 'fa-inbox',
  title = 'Nothing here yet',
  message = '',
  action = null,
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <i className={`fa-solid ${icon}`} />
      </div>
      <div style={{ fontWeight: 600, color: 'var(--tx2)', marginBottom: 6 }}>
        {title}
      </div>
      {message && (
        <div style={{ fontSize: '.85rem', maxWidth: 360, margin: '0 auto' }}>
          {message}
        </div>
      )}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
