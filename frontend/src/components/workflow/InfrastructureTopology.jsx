/**
 * InfrastructureTopology — the deployed architecture (Section 4 of the
 * Infrastructure Dashboard), drawn with plain cards + connectors (no external
 * diagram library). A vertical request flow from the public internet down to
 * the database, each connector labelled with how the tiers relate, plus a small
 * aside of attached resources (S3, ECR).
 *
 * Props:
 *  - data: { region, flow: [{ key, label, detail, icon, brand, tone, via }], attached: [...] }
 */
export default function InfrastructureTopology({ data }) {
  if (!data) return null;

  return (
    <div className="topo">
      <div className="topo-flow">
        {data.flow.map((node, i) => (
          <div className="topo-step" key={node.key}>
            <div className={`topo-node topo-${node.tone || 'neutral'}`}>
              <span className="topo-ico">
                <i className={`${node.brand ? 'fa-brands' : 'fa-solid'} ${node.icon}`} />
              </span>
              <div style={{ minWidth: 0 }}>
                <div className="topo-label">{node.label}</div>
                {node.detail && <div className="topo-detail">{node.detail}</div>}
              </div>
            </div>
            {i < data.flow.length - 1 && (
              <div className="topo-connector">
                <span className="topo-line" />
                <i className="fa-solid fa-chevron-down topo-arrow" />
                {node.via && <span className="topo-via">{node.via}</span>}
              </div>
            )}
          </div>
        ))}
      </div>

      {data.attached && data.attached.length > 0 && (
        <div className="topo-aside">
          <div className="topo-aside-label">
            <i className="fa-solid fa-link me-2" />
            Attached Resources
          </div>
          {data.attached.map((a) => (
            <div className="topo-aside-node" key={a.key}>
              <span className="topo-ico topo-ico-sm">
                <i className={`${a.brand ? 'fa-brands' : 'fa-solid'} ${a.icon}`} />
              </span>
              <div style={{ minWidth: 0 }}>
                <div className="topo-label">{a.label}</div>
                {a.detail && <div className="topo-detail mono">{a.detail}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
