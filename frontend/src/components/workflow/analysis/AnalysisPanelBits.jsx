/* ============================================================================
   AnalysisPanelBits.jsx — small shared presentational helpers used across the
   Workflow Analysis panels. Kept tiny and dependency-free so each panel stays
   modular without duplicating chrome.
   ========================================================================== */
import Tag from '@/components/common/Tag';

// Non-component helpers (SEV_VARIANT, scoreColor) live in ./analysisHelpers so
// this file exports only components (react-refresh/only-export-components).

/** Small section sub-heading inside a panel. */
export function Subhead({ children, className = '' }) {
  return (
    <div className={`form-label-sm ${className}`.trim()} style={{ marginBottom: 6 }}>
      {children}
    </div>
  );
}

/**
 * TagRow — render a list of tags (strings or {name,version,icon,brand}). Shows
 * an `empty` hint when the list is missing/empty (no blank white space).
 */
export function TagRow({ items, empty = 'None detected' }) {
  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    return <span className="text-muted-3" style={{ fontSize: '.8rem' }}>{empty}</span>;
  }
  return (
    <div className="d-flex flex-wrap gap-2">
      {list.map((it, i) => {
        const obj = typeof it === 'string' ? { name: it } : it || {};
        return (
          <Tag key={obj.name || i} icon={obj.icon} brand={obj.brand}>
            {obj.name}
            {obj.version && (
              <span className="text-muted-3 ms-1" style={{ fontSize: '.66rem' }}>
                {obj.version}
              </span>
            )}
          </Tag>
        );
      })}
    </div>
  );
}

/** Bulleted recommendation/observation list (reuses the .check-list styling). */
export function CheckList({ items, icon = 'fa-circle-check', warn = false, empty }) {
  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    return empty ? (
      <span className="text-muted-3" style={{ fontSize: '.8rem' }}>{empty}</span>
    ) : null;
  }
  return (
    <ul className={`check-list ${warn ? 'warn' : ''}`.trim()}>
      {list.map((t, i) => (
        <li key={i}>
          <i className={`fa-solid ${warn ? 'fa-triangle-exclamation' : icon}`} />
          <span>{t}</span>
        </li>
      ))}
    </ul>
  );
}

/** Labelled recommendation row with an icon (reuses the .reco-row styling). */
export function RecoRow({ icon = 'fa-circle-check', title, detail }) {
  return (
    <div className="reco-row">
      <span className="reco-ico"><i className={`fa-solid ${icon}`} /></span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: '.86rem' }}>{title}</div>
        {detail && (
          <p className="mb-0" style={{ fontSize: '.8rem', color: 'var(--tx3)' }}>{detail}</p>
        )}
      </div>
    </div>
  );
}

/** Severity tally chip (e.g. "Critical 0"). */
export function SevChip({ label, n = 0, variant }) {
  return (
    <span className="d-inline-flex align-items-center gap-2">
      <span
        className={`badge-pill badge-${n > 0 ? variant : 'pending'}`}
        style={{ minWidth: 26, justifyContent: 'center' }}
      >
        {n}
      </span>
      <span style={{ color: 'var(--tx3)' }}>{label}</span>
    </span>
  );
}
