/**
 * LoadingSpinner — brand-colored spinner. `center` wraps it in a padded,
 * centered block suitable for page/section loading states.
 */
export default function LoadingSpinner({ center = false, label }) {
  const spinner = (
    <div className="d-inline-flex align-items-center gap-2">
      <span className="spinner" />
      {label && (
        <span style={{ fontSize: '.85rem', color: 'var(--tx3)' }}>{label}</span>
      )}
    </div>
  );

  if (center) return <div className="spinner-center">{spinner}</div>;
  return spinner;
}
