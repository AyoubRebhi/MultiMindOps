/**
 * ErrorState — inline error placeholder with an optional Retry action.
 * Mirrors <EmptyState> styling so failed widgets stay visually consistent.
 *
 * Props:
 *  - title: headline (default "Couldn't load data")
 *  - message: detail copy (e.g. the API error message)
 *  - onRetry: callback — renders a Retry button when provided
 *  - compact: tighter padding for in-card use
 */
export default function ErrorState({
  title = "Couldn't load data",
  message = 'Something went wrong while talking to the server.',
  onRetry,
  compact = false,
}) {
  return (
    <div className="empty-state" style={compact ? { padding: '24px 16px' } : undefined}>
      <div className="empty-icon" style={{ color: '#f87171' }}>
        <i className="fa-solid fa-triangle-exclamation" />
      </div>
      <div style={{ fontWeight: 600, color: 'var(--tx2)', marginBottom: 6 }}>{title}</div>
      {message && (
        <div style={{ fontSize: '.85rem', maxWidth: 360, margin: '0 auto' }}>{message}</div>
      )}
      {onRetry && (
        <div className="mt-3">
          <button type="button" className="boc btn px-3 py-2" onClick={onRetry}>
            <i className="fa-solid fa-rotate-right me-2" />
            Retry
          </button>
        </div>
      )}
    </div>
  );
}
