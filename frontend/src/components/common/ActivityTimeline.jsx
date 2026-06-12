import { timeAgo } from '@/utils/formatters';

const TYPE_COLOR = {
  success: '#34d399',
  running: '#60a5fa',
  warning: '#fbbf24',
  danger: '#f87171',
  info: '#a78bfa',
};

/**
 * ActivityTimeline — vertical, node-connected feed of workspace events.
 * Reuses the .timeline styling from app.css.
 *
 * Props:
 *  - items: [{ id, type, icon, brand?, actor?, message, at }]
 *  - max: cap rendered items
 */
export default function ActivityTimeline({ items = [], max }) {
  const list = max ? items.slice(0, max) : items;

  if (!list.length) {
    return (
      <div className="text-muted-3" style={{ fontSize: '.85rem' }}>
        No recent activity.
      </div>
    );
  }

  return (
    <div className="timeline">
      {list.map((item) => {
        const color = TYPE_COLOR[item.type] || 'var(--tx2)';
        return (
          <div className="timeline-item" key={item.id}>
            <span
              className="timeline-node"
              style={{ borderColor: color, color, background: `${color}22` }}
            >
              <i className={`${item.brand ? 'fa-brands' : 'fa-solid'} ${item.icon}`} />
            </span>
            <div className="d-flex align-items-start justify-content-between gap-2">
              <div style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>
                {item.actor && (
                  <span style={{ fontWeight: 600, color: 'var(--tx)' }}>{item.actor} </span>
                )}
                {item.message}
              </div>
              <span
                style={{ fontSize: '.7rem', color: 'var(--tx3)', whiteSpace: 'nowrap' }}
              >
                {timeAgo(item.at)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
