import { createContext, useCallback, useMemo, useRef, useState } from 'react';

/**
 * ToastContext — lightweight, dependency-free toast notifications.
 *
 * Mounted once near the app root (see main.jsx). Any component can raise a
 * toast via the useToast() hook:
 *   const toast = useToast();
 *   toast.error('Failed to load metrics');
 *
 * Self-contained: styling is inline against the design-system CSS variables so
 * it needs no global stylesheet changes.
 */
// eslint-disable-next-line react-refresh/only-export-components
export const ToastContext = createContext(null);

let _seq = 0;

const TYPE_META = {
  success: { color: '#34d399', icon: 'fa-circle-check' },
  danger: { color: '#f87171', icon: 'fa-triangle-exclamation' },
  info: { color: '#60a5fa', icon: 'fa-circle-info' },
  warning: { color: '#fbbf24', icon: 'fa-triangle-exclamation' },
};

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef({});

  const dismiss = useCallback((id) => {
    setToasts((list) => list.filter((t) => t.id !== id));
    const handle = timers.current[id];
    if (handle) {
      clearTimeout(handle);
      delete timers.current[id];
    }
  }, []);

  const push = useCallback(
    (toast) => {
      const id = ++_seq;
      const item = { id, type: 'info', duration: 5000, ...toast };
      setToasts((list) => [...list, item]);
      if (item.duration > 0) {
        timers.current[id] = setTimeout(() => dismiss(id), item.duration);
      }
      return id;
    },
    [dismiss]
  );

  const api = useMemo(
    () => ({
      push,
      dismiss,
      success: (message, opts = {}) => push({ ...opts, type: 'success', message }),
      error: (message, opts = {}) => push({ ...opts, type: 'danger', message }),
      info: (message, opts = {}) => push({ ...opts, type: 'info', message }),
      warning: (message, opts = {}) => push({ ...opts, type: 'warning', message }),
    }),
    [push, dismiss]
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

function ToastViewport({ toasts, onDismiss }) {
  if (!toasts.length) return null;
  return (
    <div
      style={{
        position: 'fixed',
        right: 20,
        bottom: 20,
        zIndex: 1080,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        maxWidth: 'min(380px, calc(100vw - 40px))',
      }}
      role="region"
      aria-label="Notifications"
      aria-live="polite"
    >
      {toasts.map((t) => {
        const meta = TYPE_META[t.type] || TYPE_META.info;
        return (
          <div
            key={t.id}
            className="surface"
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 12,
              padding: '12px 14px',
              borderLeft: `3px solid ${meta.color}`,
              boxShadow: '0 8px 24px rgba(0,0,0,.35)',
              animation: 'none',
            }}
          >
            <i
              className={`fa-solid ${meta.icon}`}
              style={{ color: meta.color, marginTop: 2 }}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              {t.title && (
                <div style={{ fontWeight: 600, fontSize: '.85rem', marginBottom: 2 }}>
                  {t.title}
                </div>
              )}
              <div style={{ fontSize: '.82rem', color: 'var(--tx2)', wordBreak: 'break-word' }}>
                {t.message}
              </div>
            </div>
            <button
              type="button"
              onClick={() => onDismiss(t.id)}
              aria-label="Dismiss"
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--tx3)',
                cursor: 'pointer',
                fontSize: '.85rem',
                lineHeight: 1,
                padding: 2,
              }}
            >
              <i className="fa-solid fa-xmark" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
