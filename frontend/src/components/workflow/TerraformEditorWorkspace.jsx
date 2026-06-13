import { useEffect, useMemo, useState } from 'react';

/**
 * TerraformEditorWorkspace — the manual correction workspace shown after a
 * validation or execution failure. Side-by-side Original vs Current file with a
 * changes indicator and an unsaved-changes badge; the user can apply the
 * suggested fix, edit freely, Save / Discard, then Revalidate or Retry.
 *
 * Props:
 *  - fileName
 *  - original: the originally generated file content
 *  - value: the current saved content (controlled by the page)
 *  - suggestion: optional suggested-fix content
 *  - context: 'validation' | 'execution' | 'review' (drives the primary action)
 *  - note: optional one-line explanation of the suggested fix
 *  - onSave(next), onRevalidate(), onRetry(), onClose()
 */
function lineSet(text) {
  return new Set(
    (text || '').replace(/\n$/, '').split('\n').map((l) => l.trim()).filter(Boolean)
  );
}

function DiffPre({ text, otherSet, mark }) {
  const lines = (text || '').replace(/\n$/, '').split('\n');
  return (
    <pre className="diff-pre mono">
      {lines.map((l, i) => {
        const t = l.trim();
        const changed = t && !otherSet.has(t);
        return (
          <div key={i} className={`diff-line ${changed ? `is-${mark}` : ''}`.trim()}>
            <span className="diff-sign">{changed ? (mark === 'del' ? '-' : '+') : ' '}</span>
            <span>{l || ' '}</span>
          </div>
        );
      })}
    </pre>
  );
}

export default function TerraformEditorWorkspace({
  fileName,
  original = '',
  value = '',
  suggestion = null,
  context = 'validation',
  note,
  onSave,
  onRevalidate,
  onRetry,
  onClose,
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  const current = editing ? draft : value;
  const origSet = useMemo(() => lineSet(original), [original]);
  const currSet = useMemo(() => lineSet(current), [current]);

  const added = (current.replace(/\n$/, '').split('\n')).filter(
    (l) => l.trim() && !origSet.has(l.trim())
  ).length;
  const removed = (original.replace(/\n$/, '').split('\n')).filter(
    (l) => l.trim() && !currSet.has(l.trim())
  ).length;

  const changed = value !== original;
  const unsaved = editing && draft !== value;

  const save = () => {
    onSave?.(draft);
    setEditing(false);
  };
  const discard = () => {
    setDraft(value);
    setEditing(false);
  };
  const applySuggestion = () => {
    if (suggestion == null) return;
    setDraft(suggestion);
    setEditing(true);
  };

  const primary =
    context === 'execution'
      ? { label: 'Retry Execution', icon: 'fa-rotate', onClick: onRetry }
      : context === 'validation'
        ? { label: 'Revalidate', icon: 'fa-rotate', onClick: onRevalidate }
        : null;

  return (
    <div className="surface tf-workspace">
      <div className="phase-card-head">
        <div className="d-flex align-items-center gap-3" style={{ minWidth: 0 }}>
          <span className="tf-ws-badge">
            <i className="fa-solid fa-screwdriver-wrench" />
          </span>
          <div style={{ minWidth: 0 }}>
            <h3 className="card-title">Manual Correction Workspace</h3>
            <p className="phase-card-subtitle mono">{fileName}</p>
          </div>
        </div>
        <div className="d-flex align-items-center gap-2 flex-wrap">
          <span className={`badge-pill ${changed ? 'badge-running' : 'badge-pending'}`}>
            <i className="fa-solid fa-code-compare" />
            {changed ? `Modified +${added} −${removed}` : 'No changes'}
          </span>
          {unsaved && (
            <span className="badge-pill badge-warning">
              <i className="fa-solid fa-circle" style={{ fontSize: '.5rem' }} />
              Unsaved changes
            </span>
          )}
        </div>
      </div>

      {note && (
        <div className="tf-ws-note">
          <i className="fa-solid fa-lightbulb me-2" style={{ color: '#a78bfa' }} />
          {note}
        </div>
      )}

      <div className="tf-ws-cols">
        <div className="diff-col">
          <div className="diff-col-head">
            <i className="fa-solid fa-file-circle-minus me-2" />Original File
          </div>
          <DiffPre text={original} otherSet={currSet} mark="del" />
        </div>
        <div className="diff-col">
          <div className="diff-col-head tf-ws-current-head">
            <span><i className="fa-solid fa-file-pen me-2" />Current File</span>
            {!editing ? (
              <button type="button" className="tf-ws-mini" onClick={() => setEditing(true)}>
                <i className="fa-solid fa-pen me-1" />Edit
              </button>
            ) : (
              <span className="d-inline-flex gap-2">
                <button type="button" className="tf-ws-mini" onClick={discard}>
                  <i className="fa-solid fa-xmark me-1" />Discard
                </button>
                <button type="button" className="tf-ws-mini is-primary" onClick={save}>
                  <i className="fa-solid fa-floppy-disk me-1" />Save
                </button>
              </span>
            )}
          </div>
          {editing ? (
            <textarea
              className="tf-ws-area mono"
              value={draft}
              spellCheck={false}
              onChange={(e) => setDraft(e.target.value)}
            />
          ) : (
            <DiffPre text={value} otherSet={origSet} mark="add" />
          )}
        </div>
      </div>

      <div className="tf-panel-actions tf-ws-foot">
        {suggestion != null && !changed && (
          <button type="button" className="boc btn px-3 py-2 code-action" onClick={applySuggestion}>
            <i className="fa-solid fa-wand-magic-sparkles me-2" />Apply suggested fix
          </button>
        )}
        <button type="button" className="boc btn px-3 py-2 code-action" onClick={onClose}>
          <i className="fa-solid fa-xmark me-2" />Close
        </button>
        {primary && (
          <button
            type="button"
            className="bgrd btn px-3 py-2 code-action"
            onClick={primary.onClick}
          >
            <i className={`fa-solid ${primary.icon} me-2`} />{primary.label}
          </button>
        )}
      </div>
    </div>
  );
}
