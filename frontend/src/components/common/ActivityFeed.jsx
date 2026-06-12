import { timeAgo } from '@/utils/formatters';

const TYPE_COLOR = {
  success: '#34d399',
  running: '#60a5fa',
  warning: '#fbbf24',
  danger: '#f87171',
  info: '#a78bfa',
};

/**
 * ActivityFeed — vertical list of recent platform events.
 *
 * Props:
 *  - items: [{ id, type, icon, message, at }]
 *  - max: limit rendered items
 */
export default function ActivityFeed({ items = [], max }) {
  const list = max ? items.slice(0, max) : items;

  if (!list.length) {
    return (
      <div className="text-muted-3" style={{ fontSize: '.85rem' }}>
        No recent activity.
      </div>
    );
  }

  return (
    <div className="d-flex flex-column gap-2">
      {list.map((item) => {
        const color = TYPE_COLOR[item.type] || 'var(--tx2)';
        const spin = item.type === 'running';
        return (
          <div
            key={item.id}
            className="d-flex gap-3 align-items-start"
            style={{
              padding: '10px 12px',
              background: 'var(--bg3)',
              borderRadius: 10,
            }}
          >
            <div
              className="icon-tile"
              style={{
                width: 30,
                height: 30,
                fontSize: '.8rem',
                background: 'var(--sf)',
                color,
              }}
            >
              <i className={`fa-solid ${item.icon} ${spin ? 'fa-spin' : ''}`.trim()} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: '.82rem', color: 'var(--tx2)' }}>
                {item.message}
              </div>
              <div style={{ fontSize: '.7rem', color: 'var(--tx3)', marginTop: 2 }}>
                <i className="fa-regular fa-clock me-1" />
                {timeAgo(item.at)}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
