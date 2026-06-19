import { useState } from 'react';

/**
 * DockerfileViewer — READ-ONLY view of a generated Dockerfile, rendered straight
 * from the backend (no editing, no mock content). Line-numbered, with a header
 * carrying the filename, persisted version, approval state and a copy button.
 *
 * Props:
 *  - content      Dockerfile text (required)
 *  - filename     default "Dockerfile"
 *  - version      persisted artifact version (optional)
 *  - approvalState 'approved' | 'pending_review' | 'rejected' (optional)
 *  - edited       the live file diverges from the originally generated one
 *  - title        optional eyebrow shown in the header (e.g. "Approved Dockerfile")
 */
const APPROVAL_META = {
  approved: { label: 'Approved', variant: 'success', icon: 'fa-circle-check' },
  pending_review: { label: 'Pending review', variant: 'warning', icon: 'fa-hourglass-half' },
  rejected: { label: 'Rejected', variant: 'danger', icon: 'fa-circle-xmark' },
};

export default function DockerfileViewer({
  content = '',
  filename = 'Dockerfile',
  version = null,
  approvalState = null,
  edited = false,
  title = null,
}) {
  const [copied, setCopied] = useState(false);
  const lines = content.split('\n');
  const approval = approvalState ? APPROVAL_META[approvalState] : null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — non-fatal */
    }
  };

  return (
    <div className="surface" style={{ padding: 0, overflow: 'hidden' }}>
      <div
        className="d-flex align-items-center gap-2 flex-wrap"
        style={{ padding: '10px 14px', borderBottom: '1px solid var(--bd)' }}
      >
        <i className="fa-brands fa-docker" style={{ color: '#2496ed' }} />
        <span style={{ fontWeight: 600, fontSize: '.85rem' }}>{filename}</span>
        {title && (
          <span className="badge-pill badge-success" style={{ marginLeft: 2 }}>
            <i className="fa-solid fa-shield-halved me-1" />
            {title}
          </span>
        )}
        {version != null && (
          <span className="tag" style={{ fontSize: '.72rem' }}>v{version}</span>
        )}
        {approval && (
          <span className={`badge-pill badge-${approval.variant}`}>
            <i className={`fa-solid ${approval.icon} me-1`} />
            {approval.label}
          </span>
        )}
        {edited && (
          <span className="badge-pill badge-info" title="Differs from the originally generated Dockerfile">
            <i className="fa-solid fa-pen me-1" />
            Edited
          </span>
        )}
        <button
          type="button"
          className="boc btn ms-auto"
          style={{ fontSize: '.74rem', padding: '4px 10px' }}
          onClick={copy}
        >
          <i className={`fa-solid ${copied ? 'fa-check' : 'fa-copy'} me-1`} />
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>

      <div className="code-viewer" style={{ maxHeight: 460, overflow: 'auto' }}>
        <pre style={{ margin: 0, padding: '12px 0', fontSize: '.8rem', lineHeight: 1.55 }}>
          {lines.map((line, i) => (
            <div key={i} className="code-line" style={{ display: 'flex' }}>
              <span
                aria-hidden
                style={{
                  display: 'inline-block',
                  width: 44,
                  flexShrink: 0,
                  textAlign: 'right',
                  paddingRight: 14,
                  color: 'var(--tx3)',
                  userSelect: 'none',
                }}
              >
                {i + 1}
              </span>
              <code style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {line || ' '}
              </code>
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}
