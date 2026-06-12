/**
 * Skeleton — shimmer placeholder block. Compose several to mimic a card's
 * layout while data loads.
 *
 * Props: width, height (CSS sizes), radius (px), className
 */
export default function Skeleton({
  width = '100%',
  height = 16,
  radius = 8,
  className = '',
}) {
  return (
    <span
      className={`skeleton d-block ${className}`.trim()}
      style={{ width, height, borderRadius: radius }}
    />
  );
}

/** A simple skeleton card matching the surface card footprint. */
export function SkeletonCard() {
  return (
    <div className="surface">
      <Skeleton width="42px" height={42} radius={12} />
      <Skeleton width="60%" height={18} className="mt-3" />
      <Skeleton width="90%" height={12} className="mt-2" />
      <Skeleton width="40%" height={12} className="mt-2" />
    </div>
  );
}
