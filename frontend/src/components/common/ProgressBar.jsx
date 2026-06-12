import { clampPercent } from '@/utils/formatters';

/**
 * ProgressBar — thin gradient progress indicator.
 *
 * Props:
 *  - value: 0–100
 *  - showLabel: render the percentage to the right
 *  - height: track height in px (default 6)
 */
export default function ProgressBar({ value = 0, showLabel = false, height = 6 }) {
  const pct = clampPercent(value);
  return (
    <div className="d-flex align-items-center gap-2">
      <div className="progress-track flex-grow-1" style={{ height }}>
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      {showLabel && (
        <span
          style={{
            fontSize: '.72rem',
            fontWeight: 600,
            color: 'var(--tx3)',
            minWidth: 34,
            textAlign: 'right',
          }}
        >
          {pct}%
        </span>
      )}
    </div>
  );
}
