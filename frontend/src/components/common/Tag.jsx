/**
 * Tag — small chip for tech stack, labels, metadata.
 *
 * Props:
 *  - icon: optional Font Awesome class
 *  - brand: use fa-brands instead of fa-solid for the icon
 *  - children: label
 */
export default function Tag({ icon, brand = false, children, className = '' }) {
  return (
    <span className={`tag ${className}`.trim()}>
      {icon && <i className={`${brand ? 'fa-brands' : 'fa-solid'} ${icon}`} />}
      {children}
    </span>
  );
}
