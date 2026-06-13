/**
 * TerraformResourceSummary — the grouped resource breakdown (Networking,
 * Compute, Database, Storage) the configuration would create. Used both in the
 * review step (counts) and in the final success result (with ✓ checks).
 *
 * Props:
 *  - resources: [{ group, icon, accent, items: [{ name, count, icon }] }]
 *  - checked: render a green ✓ per item (success/result mode)
 */
export default function TerraformResourceSummary({ resources = [], checked = false }) {
  return (
    <div className="row g-3">
      {resources.map((group) => (
        <div className="col-md-6" key={group.group}>
          <div className="tf-res-group">
            <div className="tf-res-group-head">
              <span className="tf-res-group-ico" style={{ color: group.accent }}>
                <i className={`fa-solid ${group.icon}`} />
              </span>
              <span className="tf-res-group-name">{group.group}</span>
              <span className="tf-res-group-count">
                {group.items.reduce((s, i) => s + i.count, 0)}
              </span>
            </div>
            <ul className="tf-res-list">
              {group.items.map((item) => (
                <li className="tf-res-item" key={item.name}>
                  <span className="tf-res-item-left">
                    {checked ? (
                      <i className="fa-solid fa-circle-check tf-res-check" />
                    ) : (
                      <i className={`fa-solid ${item.icon} tf-res-item-ico`} />
                    )}
                    <span className="tf-res-item-name">{item.name}</span>
                  </span>
                  <span className="tf-res-item-count">×{item.count}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ))}
    </div>
  );
}
