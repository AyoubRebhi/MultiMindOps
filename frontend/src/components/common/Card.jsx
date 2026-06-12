/**
 * Card — generic surface container with an optional header (title + action).
 *
 * Props:
 *  - title: string | node (optional header title)
 *  - icon: Font Awesome class for the title (optional)
 *  - action: node rendered on the right of the header (e.g. a link/button)
 *  - hover: enable hover-lift effect
 *  - bodyClassName / className: style hooks
 *  - children: card body
 */
export default function Card({
  title,
  icon,
  action,
  hover = false,
  className = '',
  bodyClassName = '',
  children,
}) {
  return (
    <div className={`surface ${hover ? 'surface-hover' : ''} ${className}`.trim()}>
      {(title || action) && (
        <div className="d-flex align-items-center justify-content-between mb-3">
          <h3 className="card-title">
            {icon && (
              <i
                className={`fa-solid ${icon} me-2`}
                style={{ color: 'var(--pur)' }}
              />
            )}
            {title}
          </h3>
          {action}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </div>
  );
}
