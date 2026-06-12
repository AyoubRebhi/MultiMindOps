import { useEffect } from 'react';
import { createPortal } from 'react-dom';

/**
 * Modal — lightweight, dependency-free dialog (no bootstrap JS). Renders into a
 * portal on <body>, closes on backdrop click + Escape, and locks body scroll.
 *
 * Props:
 *  - open: boolean
 *  - onClose: () => void
 *  - title, icon: header
 *  - footer: node rendered in the footer (e.g. action buttons)
 *  - children: body
 *  - maxWidth: px (default 480)
 */
export default function Modal({
  open,
  onClose,
  title,
  icon,
  footer,
  children,
  maxWidth = 480,
}) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === 'Escape' && onClose?.();
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="modal-overlay" onMouseDown={onClose}>
      <div
        className="modal-card"
        style={{ maxWidth }}
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {(title || icon) && (
          <div className="modal-header">
            <h3 className="card-title">
              {icon && (
                <i className={`fa-solid ${icon} me-2`} style={{ color: 'var(--pur)' }} />
              )}
              {title}
            </h3>
            <button className="dd-close" onClick={onClose} aria-label="Close">
              <i className="fa-solid fa-xmark" />
            </button>
          </div>
        )}
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>,
    document.body
  );
}
