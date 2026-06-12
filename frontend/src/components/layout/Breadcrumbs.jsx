import { Link } from 'react-router-dom';

/**
 * Breadcrumbs — trail of navigation links. The last item is rendered as the
 * current (non-link) crumb.
 *
 * Props:
 *  - items: [{ label, to? }]  — items without `to` render as plain text
 */
export default function Breadcrumbs({ items = [] }) {
  if (!items.length) return null;

  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <Link to="/">
        <i className="fa-solid fa-house" />
      </Link>
      {items.map((item, i) => {
        const isLast = i === items.length - 1;
        return (
          <span key={`${item.label}-${i}`} className="d-inline-flex align-items-center gap-1">
            <i className="fa-solid fa-chevron-right fa-2xs sep" />
            {item.to && !isLast ? (
              <Link to={item.to}>{item.label}</Link>
            ) : (
              <span className="current">{item.label}</span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
