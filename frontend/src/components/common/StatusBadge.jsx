import { getStatusMeta } from '@/utils/constants';

/**
 * StatusBadge — colored pill for any lifecycle status (completed, running,
 * failed, degraded, human_review, ...). Resolves color + icon from STATUS_META.
 *
 * Props:
 *  - status: string (required)
 *  - showIcon: boolean (default true)
 *  - showDot: boolean (default false) — small leading dot instead of an icon
 *  - className: extra classes
 */
export default function StatusBadge({
  status,
  showIcon = true,
  showDot = false,
  className = '',
}) {
  const meta = getStatusMeta(status);
  const spin = meta.variant === 'running' && meta.icon === 'fa-spinner';

  return (
    <span className={`badge-pill badge-${meta.variant} ${className}`.trim()}>
      {showDot && <span className="dot" />}
      {!showDot && showIcon && (
        <i className={`fa-solid ${meta.icon} ${spin ? 'fa-spin' : ''}`.trim()} />
      )}
      {meta.label}
    </span>
  );
}
