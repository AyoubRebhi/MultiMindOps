import { useEffect, useState } from 'react';

/**
 * DockerReviewEditor — the Docker REVIEW surface: view the real generated
 * Dockerfile artifact, Edit it, Save edits (persisted via PATCH — backend is the
 * source of truth, never React-only state), and Approve it. Mirrors the spec's
 * [ Edit ] [ Save ] [ Approve ] action bar.
 *
 * Edits are never auto-saved: the parent's onSave persists to the backend and
 * reloads the artifact. Approve is locked once the artifact is approved.
 *
 * Props:
 *  - content        latest persisted Dockerfile content (editable layer)
 *  - version        persisted artifact version (optional)
 *  - approvalState  'approved' | 'pending_review' | 'rejected' | null
 *  - edited         live content diverges from the originally generated file
 *  - saving         a save is in flight
 *  - approving      an approval is in flight
 *  - onSave(next)   persist an edit (PATCH) then reload
 *  - onApprove()    persist approval then reload
 *  - editSignal     bump to force-open edit mode (from "Edit Manually")
 */
const INSTRUCTIONS = new Set([
  'FROM', 'RUN', 'CMD', 'LABEL', 'EXPOSE', 'ENV', 'ADD', 'COPY', 'ENTRYPOINT',
  'VOLUME', 'USER', 'WORKDIR', 'ARG', 'ONBUILD', 'STOPSIGNAL', 'HEALTHCHECK',
  'SHELL', 'MAINTAINER',
]);

function highlightLine(line, key) {
  if (line.trim().startsWith('#')) {
    return <div className="cl" key={key}><span className="tok-comment">{line || ' '}</span></div>;
  }
  const m = line.match(/^(\s*)([A-Za-z]+)(\s+)(.*)$/);
  if (m && INSTRUCTIONS.has(m[2].toUpperCase())) {
    const [, lead, instr, gap, rest] = m;
    return (
      <div className="cl" key={key}>
        {lead}
        <span className="tok-instr">{instr}</span>
        {gap}
        {rest}
      </div>
    );
  }
  return <div className="cl" key={key}>{line || ' '}</div>;
}

export default function DockerReviewEditor({
  content = '',
  version = null,
  approvalState = null,
  edited = false,
  saving = false,
  approving = false,
  onSave,
  onApprove,
  editSignal = 0,
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(content);

  // Keep the draft synced with the persisted content when not actively editing.
  useEffect(() => {
    if (!editing) setDraft(content);
  }, [content, editing]);

  // Open edit mode on demand (corrector's "Edit Manually").
  useEffect(() => {
    if (editSignal > 0) {
      setDraft(content);
      setEditing(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editSignal]);

  const lines = content.replace(/\n$/, '').split('\n');
  const approved = approvalState === 'approved';

  const save = () => {
    onSave?.(draft);
    setEditing(false);
  };
  const cancel = () => {
    setDraft(content);
    setEditing(false);
  };

  return (
    <div className="code-editor">
      <div className="code-editor-head">
        <div className="d-flex align-items-center gap-2" style={{ minWidth: 0 }}>
          <i className="fa-brands fa-docker" style={{ color: '#2496ed' }} />
          <span className="code-editor-name mono">Dockerfile</span>
          {version != null && <span className="tag" style={{ fontSize: '.7rem' }}>v{version}</span>}
          {approved && (
            <span className="badge-pill badge-success" style={{ fontSize: '.7rem' }}>
              <i className="fa-solid fa-circle-check" />Approved
            </span>
          )}
          {edited && !approved && (
            <span className="badge-pill badge-info" style={{ fontSize: '.7rem' }} title="Differs from the originally generated Dockerfile">
              <i className="fa-solid fa-pen" />Edited
            </span>
          )}
          {editing && (
            <span className="badge-pill badge-warning" style={{ fontSize: '.7rem' }}>
              <i className="fa-solid fa-pen" />Editing
            </span>
          )}
        </div>
        <span className="code-editor-meta">{lines.length} lines</span>
      </div>

      {editing ? (
        <textarea
          className="code-editor-area mono"
          value={draft}
          spellCheck={false}
          onChange={(e) => setDraft(e.target.value)}
          rows={Math.min(Math.max(lines.length + 1, 12), 28)}
        />
      ) : (
        <pre className="code-editor-body mono">
          {lines.map((l, i) => highlightLine(l, i))}
        </pre>
      )}

      <div className="code-editor-foot">
        {editing ? (
          <>
            <button type="button" className="boc btn px-3 py-2 code-action" disabled={saving} onClick={cancel}>
              <i className="fa-solid fa-xmark me-2" />Cancel
            </button>
            <button type="button" className="bgrd btn px-3 py-2 code-action" disabled={saving} onClick={save}>
              {saving ? <span className="spinner me-2" /> : <i className="fa-solid fa-floppy-disk me-2" />}
              Save
            </button>
          </>
        ) : (
          <>
            <button type="button" className="boc btn px-3 py-2 code-action" onClick={() => setEditing(true)}>
              <i className="fa-solid fa-pen me-2" />Edit
            </button>
            <button
              type="button"
              className="bgrd btn px-3 py-2 code-action"
              disabled={approved || approving}
              onClick={() => onApprove?.()}
            >
              {approving ? <span className="spinner me-2" /> : <i className="fa-solid fa-check me-2" />}
              {approved ? 'Approved' : 'Approve'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
