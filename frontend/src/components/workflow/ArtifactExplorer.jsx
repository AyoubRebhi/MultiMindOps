import { useState } from 'react';
import { formatDate } from '@/utils/formatters';

/**
 * ArtifactExplorer — browse the artifacts produced during the run (Section 5 of
 * the Execution Center, Section 7 of the Infrastructure Dashboard). Each
 * artifact supports View (inline text preview), Download (blob of the preview,
 * or a JSON descriptor when there's no text) and Details (the metadata rows).
 * MOCK ONLY — nothing leaves the browser beyond the local download blob.
 *
 * Props:
 *  - artifacts: [{ id, name, type, kind, icon, brand, size, producedBy,
 *                  createdAt, description, details[], preview }]
 */
export default function ArtifactExplorer({ artifacts = [] }) {
  const [openId, setOpenId] = useState(null);
  const [mode, setMode] = useState('view'); // view | details

  const toggle = (id, nextMode) => {
    if (openId === id && mode === nextMode) {
      setOpenId(null);
      return;
    }
    setOpenId(id);
    setMode(nextMode);
  };

  const download = (art) => {
    const content =
      art.preview != null
        ? art.preview
        : JSON.stringify(
            { name: art.name, type: art.type, size: art.size, ...Object.fromEntries((art.details || []).map((d) => [d.label, d.value])) },
            null,
            2,
          );
    const filename = art.preview != null ? art.name.replace(/\/$/, '') || art.name : `${art.name.replace(/[^\w.-]/g, '_')}.json`;
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="artf-list">
      {artifacts.map((art) => {
        const open = openId === art.id;
        return (
          <div className={`artf-item ${open ? 'is-open' : ''}`.trim()} key={art.id}>
            <div className="artf-head">
              <span className="artf-ico">
                <i className={`${art.brand ? 'fa-brands' : 'fa-solid'} ${art.icon}`} />
              </span>
              <div className="artf-info">
                <div className="artf-name mono">{art.name}</div>
                <div className="artf-meta">
                  <span className="tag">{art.type}</span>
                  <span className="artf-dot">·</span>
                  <span>{art.size}</span>
                  <span className="artf-dot">·</span>
                  <span>{art.producedBy}</span>
                </div>
              </div>
              <div className="artf-actions">
                <button
                  type="button"
                  className={`artf-btn ${open && mode === 'view' ? 'is-active' : ''}`.trim()}
                  onClick={() => toggle(art.id, 'view')}
                >
                  <i className="fa-solid fa-eye me-1" />View
                </button>
                <button type="button" className="artf-btn" onClick={() => download(art)}>
                  <i className="fa-solid fa-download me-1" />Download
                </button>
                <button
                  type="button"
                  className={`artf-btn ${open && mode === 'details' ? 'is-active' : ''}`.trim()}
                  onClick={() => toggle(art.id, 'details')}
                >
                  <i className="fa-solid fa-circle-info me-1" />Details
                </button>
              </div>
            </div>

            {open && (
              <div className="artf-panel">
                {mode === 'view' ? (
                  art.preview != null ? (
                    <pre className="code-block artf-preview">{art.preview}</pre>
                  ) : (
                    <div className="artf-nopreview">
                      <i className="fa-solid fa-image me-2" />
                      No text preview — this is a binary artifact. Use Details for its metadata.
                    </div>
                  )
                ) : (
                  <>
                    <p className="artf-desc">{art.description}</p>
                    <div className="artf-detail-grid">
                      {(art.details || []).map((d) => (
                        <div className="artf-detail" key={d.label}>
                          <span className="artf-detail-label">{d.label}</span>
                          <span className="artf-detail-val mono">{d.value}</span>
                        </div>
                      ))}
                      <div className="artf-detail">
                        <span className="artf-detail-label">Created</span>
                        <span className="artf-detail-val">{formatDate(art.createdAt)}</span>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
