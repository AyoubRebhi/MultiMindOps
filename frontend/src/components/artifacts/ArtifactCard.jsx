import StatusBadge from '@/components/common/StatusBadge';
import { ARTIFACT_TYPES } from '@/utils/constants';
import { timeAgo } from '@/utils/formatters';

/**
 * ArtifactCard — a generated artifact (Dockerfile, Terraform, K8s, ...) with a
 * collapsible code preview. Purely presentational.
 *
 * Props:
 *  - artifact: { type, name, path, status, sizeKb, updatedAt, content, language }
 *  - showPreview: render the code snippet (default true)
 */
export default function ArtifactCard({ artifact, showPreview = true }) {
  if (!artifact) return null;
  const { type, name, path, status, sizeKb, updatedAt, content } = artifact;
  const meta = ARTIFACT_TYPES[type] || { label: type, icon: 'fa-file-code' };

  return (
    <div className="surface surface-pad-0" style={{ overflow: 'hidden' }}>
      <div className="d-flex align-items-center justify-content-between p-3">
        <div className="d-flex align-items-center gap-2">
          <div
            className="icon-tile"
            style={{ background: 'var(--bg3)', color: 'var(--tx2)' }}
          >
            <i className={`${meta.brand ? 'fa-brands' : 'fa-solid'} ${meta.icon}`} />
          </div>
          <div>
            <div style={{ fontWeight: 600, fontSize: '.9rem' }}>{name}</div>
            <div className="mono" style={{ fontSize: '.72rem', color: 'var(--tx3)' }}>
              {path}
            </div>
          </div>
        </div>
        <StatusBadge status={status} />
      </div>

      {showPreview && content && (
        <pre className="code-block" style={{ margin: 0, borderRadius: 0, maxHeight: 220 }}>
          {content}
        </pre>
      )}

      <div
        className="d-flex align-items-center justify-content-between px-3 py-2"
        style={{ borderTop: '1px solid var(--bd)', fontSize: '.72rem' }}
      >
        <span className="tag">{meta.label}</span>
        <span className="text-muted-3">
          {sizeKb} KB · updated {timeAgo(updatedAt)}
        </span>
      </div>
    </div>
  );
}
