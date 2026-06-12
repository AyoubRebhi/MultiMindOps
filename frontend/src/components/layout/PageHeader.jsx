import Breadcrumbs from './Breadcrumbs';

/**
 * PageHeader — consistent page title block with optional breadcrumbs and a
 * right-aligned actions slot.
 *
 * Props:
 *  - title (required), subtitle
 *  - breadcrumbs: items passed to <Breadcrumbs />
 *  - actions: node rendered on the right (buttons, etc.)
 */
export default function PageHeader({ title, subtitle, breadcrumbs, actions }) {
  return (
    <div>
      {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
      <div className="page-header">
        <div>
          <h1 className="page-title">{title}</h1>
          {subtitle && <p className="page-subtitle">{subtitle}</p>}
        </div>
        {actions && (
          <div className="d-flex align-items-center gap-2 flex-shrink-0">
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}
