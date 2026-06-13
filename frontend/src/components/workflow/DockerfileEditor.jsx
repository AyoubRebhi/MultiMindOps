import { useEffect, useState } from 'react';

/**
 * DockerfileEditor — shows a generated Dockerfile with lightweight syntax
 * highlighting and an Approve / Edit / Reject action bar. In edit mode it swaps
 * to a monospace textarea with Save / Cancel. No external editor dependency.
 *
 * Props:
 *  - value: Dockerfile content (controlled by the parent)
 *  - onApprove(), onReject(): decision handlers
 *  - onChange(nextContent): fired when an edit is saved
 *  - decision: 'approved' | 'rejected' | null — reflected as a badge / locks Approve
 *  - filename: header label (default "Dockerfile")
 *  - readOnly: hide the Edit affordance
 *  - editSignal: number; when it changes the editor opens in edit mode (used by
 *    the corrector's "Modify Fix" to drop the user straight into editing)
 */

// Dockerfile instructions we recognize for highlighting.
const INSTRUCTIONS = new Set([
  'FROM', 'RUN', 'CMD', 'LABEL', 'EXPOSE', 'ENV', 'ADD', 'COPY', 'ENTRYPOINT',
  'VOLUME', 'USER', 'WORKDIR', 'ARG', 'ONBUILD', 'STOPSIGNAL', 'HEALTHCHECK',
  'SHELL', 'MAINTAINER',
]);

/** Tokenize a single Dockerfile line into highlighted spans. */
function highlightLine(line, key) {
  if (line.trim().startsWith('#')) {
    return (
      <div className="cl" key={key}>
        <span className="tok-comment">{line || ' '}</span>
      </div>
    );
  }
  const m = line.match(/^(\s*)([A-Za-z]+)(\s+)(.*)$/);
  if (m && INSTRUCTIONS.has(m[2].toUpperCase())) {
    const [, lead, instr, gap, rest] = m;
    // Highlight a trailing "AS <stage>" and the --from=<stage> flag.
    const parts = rest
      .split(/(\bAS\b|--from=\S+)/g)
      .filter((p) => p !== '');
    return (
      <div className="cl" key={key}>
        {lead}
        <span className="tok-instr">{instr}</span>
        {gap}
        {parts.map((p, i) => {
          if (p === 'AS') return <span className="tok-kw" key={i}>{p}</span>;
          if (p.startsWith('--from=')) return <span className="tok-flag" key={i}>{p}</span>;
          return <span key={i}>{p}</span>;
        })}
      </div>
    );
  }
  return (
    <div className="cl" key={key}>
      {line || ' '}
    </div>
  );
}

export default function DockerfileEditor({
  value = '',
  onApprove,
  onReject,
  onChange,
  decision = null,
  filename = 'Dockerfile',
  readOnly = false,
  editSignal = 0,
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  // Sync the draft when the parent swaps the content (e.g. corrector applied).
  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  // Open edit mode on demand (e.g. corrector's "Modify Fix").
  useEffect(() => {
    if (editSignal > 0) {
      setDraft(value);
      setEditing(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editSignal]);

  const lines = value.replace(/\n$/, '').split('\n');

  const save = () => {
    onChange?.(draft);
    setEditing(false);
  };
  const cancel = () => {
    setDraft(value);
    setEditing(false);
  };

  return (
    <div className="code-editor">
      <div className="code-editor-head">
        <div className="d-flex align-items-center gap-2" style={{ minWidth: 0 }}>
          <i className="fa-brands fa-docker" style={{ color: '#2496ed' }} />
          <span className="code-editor-name mono">{filename}</span>
          {decision === 'approved' && (
            <span className="badge-pill badge-success">
              <i className="fa-solid fa-circle-check" />Approved
            </span>
          )}
          {decision === 'rejected' && (
            <span className="badge-pill badge-danger">
              <i className="fa-solid fa-circle-xmark" />Rejected
            </span>
          )}
          {editing && (
            <span className="badge-pill badge-warning">
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
          rows={Math.min(Math.max(lines.length + 1, 12), 26)}
        />
      ) : (
        <pre className="code-editor-body mono">
          {lines.map((l, i) => highlightLine(l, i))}
        </pre>
      )}

      <div className="code-editor-foot">
        {editing ? (
          <>
            <button type="button" className="boc btn px-3 py-2 code-action" onClick={cancel}>
              <i className="fa-solid fa-xmark me-2" />Cancel
            </button>
            <button type="button" className="bgrd btn px-3 py-2 code-action" onClick={save}>
              <i className="fa-solid fa-floppy-disk me-2" />Save changes
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className="boc btn px-3 py-2 code-action code-action-danger"
              onClick={() => onReject?.()}
            >
              <i className="fa-solid fa-xmark me-2" />Reject
            </button>
            {!readOnly && (
              <button
                type="button"
                className="boc btn px-3 py-2 code-action"
                onClick={() => setEditing(true)}
              >
                <i className="fa-solid fa-pen me-2" />Edit
              </button>
            )}
            <button
              type="button"
              className="bgrd btn px-3 py-2 code-action"
              disabled={decision === 'approved'}
              onClick={() => onApprove?.()}
            >
              <i className="fa-solid fa-check me-2" />
              {decision === 'approved' ? 'Approved' : 'Approve'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
