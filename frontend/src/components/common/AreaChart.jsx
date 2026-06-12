import { useId } from 'react';

/**
 * AreaChart — tiny dependency-free SVG area chart (replaces the template's
 * Chart.js usage). Renders a smooth gradient-filled trend line.
 *
 * Props:
 *  - labels: string[]   (x-axis labels; first/last are shown)
 *  - values: number[]   (y values)
 *  - height: px (default 180)
 */
export default function AreaChart({ labels = [], values = [], height = 180 }) {
  const gradId = useId();
  const width = 600; // viewBox width; SVG scales responsively
  const pad = 8;

  if (!values.length) return null;

  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const stepX = (width - pad * 2) / (values.length - 1 || 1);

  const points = values.map((v, i) => {
    const x = pad + i * stepX;
    const y = pad + (height - pad * 2) * (1 - (v - min) / range);
    return [x, y];
  });

  const line = points.map(([x, y], i) => `${i ? 'L' : 'M'}${x},${y}`).join(' ');
  const area =
    `M${points[0][0]},${height - pad} ` +
    points.map(([x, y]) => `L${x},${y}`).join(' ') +
    ` L${points[points.length - 1][0]},${height - pad} Z`;

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        role="img"
        aria-label="Trend chart"
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#8b5cf6" stopOpacity="0.35" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#${gradId})`} />
        <path
          d={line}
          fill="none"
          stroke="#8b5cf6"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        {points.map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r="2.5" fill="#a78bfa" />
        ))}
      </svg>
      {labels.length > 0 && (
        <div
          className="d-flex justify-content-between mt-2"
          style={{ fontSize: '.68rem', color: 'var(--tx3)' }}
        >
          <span>{labels[0]}</span>
          <span>{labels[Math.floor(labels.length / 2)]}</span>
          <span>{labels[labels.length - 1]}</span>
        </div>
      )}
    </div>
  );
}
