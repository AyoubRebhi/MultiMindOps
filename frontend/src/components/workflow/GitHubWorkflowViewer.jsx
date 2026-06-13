import { Fragment, useEffect, useState } from 'react';

/**
 * GitHubWorkflowViewer — read/edit viewer for a generated GitHub Actions YAML
 * workflow. Lightweight YAML highlighter (no external dependency), line numbers,
 * expand/collapse, copy, download and inline edit, plus an Approve / Edit /
 * Reject action bar.
 *
 * Props:
 *  - value: YAML content (controlled by the parent)
 *  - filename: header label (default ".github/workflows/deploy.yml")
 *  - meta: optional { jobs, steps } shown as header chips
 *  - decision: 'approved' | 'rejected' | null — reflected as a badge / locks Approve
 *  - onApprove(), onReject(): decision handlers
 *  - onChange(next): fired when an edit is saved
 *  - readOnly: hide the Edit / decision affordances
 *  - editSignal: number; when it changes the editor opens in edit mode (used by
 *    "Fix Workflow" to drop the user straight into editing)
 *  - collapsedLines: line count before the collapse fade kicks in (default 26)
 */
const COLLAPSE_AT = 26;

/** Wrap ${{ expressions }} and "quoted strings" in highlight spans. */
function highlightInline(text, prefix) {
  const tokens = text.split(/(\$\{\{[^}]*\}\}|"[^"]*"|'[^']*')/g);
  return tokens.map((t, i) => {
    if (!t) return null;
    const key = `${prefix}-${i}`;
    if (t.startsWith('${{')) return <span className="tok-expr" key={key}>{t}</span>;
    if (t.startsWith('"') || t.startsWith("'")) return <span className="tok-str" key={key}>{t}</span>;
    return <Fragment key={key}>{t}</Fragment>;
  });
}

/** Highlight a single YAML line into colored token spans. */
function renderYaml(raw, idx) {
  if (raw.trimStart().startsWith('#')) {
    return <span className="tok-comment">{raw || ' '}</span>;
  }
  // key: value  (optionally prefixed by a "- " list dash)
  const kv = raw.match(/^(\s*)(- )?([A-Za-z0-9_.-]+)(:)(\s*)(.*)$/);
  if (kv) {
    const [, indent, dash, key, colon, gap, rest] = kv;
    return (
      <>
        {indent}
        {dash && <span className="tok-yaml-dash">{dash}</span>}
        <span className="tok-yaml-key">{key}</span>
        {colon}
        {gap}
        {highlightInline(rest, idx)}
      </>
    );
  }
  // bare list item: "- value"
  const li = raw.match(/^(\s*)(- )(.*)$/);
  if (li) {
    const [, indent, dash, rest] = li;
    return (
      <>
        {indent}
        <span className="tok-yaml-dash">{dash}</span>
        {highlightInline(rest, idx)}
      </>
    );
  }
  return highlightInline(raw || ' ', idx);
}

export default function GitHubWorkflowViewer({
  value = '',
  filename = '.github/workflows/deploy.yml',
  meta,
  decision = null,
  onApprove,
  onReject,
  onChange,
  readOnly = false,
  editSignal = 0,
  collapsedLines = COLLAPSE_AT,
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  // Keep the draft in sync when the parent swaps content (and not editing).
  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  // Open edit mode on demand (e.g. "Fix Workflow").
  useEffect(() => {
    if (editSignal > 0) {
      setDraft(value);
      setEditing(true);
      setExpanded(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editSignal]);

  const lines = value.replace(/\n$/, '').split('\n');
  const longFile = lines.length > collapsedLines;
  const showCollapse = longFile && !expanded && !editing;

  const save = () => {
    onChange?.(draft);
    setEditing(false);
  };
  const cancel = () => {
    setDraft(value);
    setEditing(false);
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — no-op in the mock */
    }
  };

  const download = () => {
    const blob = new Blob([value], { type: 'text/yaml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename.split('/').pop() || 'deploy.yml';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="gh-yaml">
      <div className="gh-yaml-head">
        <div className="d-flex align-items-center gap-2" style={{ minWidth: 0 }}>
          <i className="fa-brands fa-github" style={{ color: 'var(--tx)' }} />
          <span className="gh-yaml-name mono">{filename}</span>
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
        <div className="gh-yaml-tools">
          {meta && (
            <span className="gh-yaml-meta">
              <i className="fa-solid fa-diagram-project me-1" />{meta.jobs} jobs
              <span className="gh-yaml-dot" />
              {meta.steps} steps
            </span>
          )}
          <button type="button" className="gh-tool-btn" onClick={copy} disabled={editing}>
            <i className={`fa-solid ${copied ? 'fa-check' : 'fa-copy'} me-1`} />
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button type="button" className="gh-tool-btn" onClick={download} disabled={editing}>
            <i className="fa-solid fa-download me-1" />Download
          </button>
          {longFile && !editing && (
            <button type="button" className="gh-tool-btn" onClick={() => setExpanded((v) => !v)}>
              <i className={`fa-solid ${expanded ? 'fa-compress' : 'fa-expand'} me-1`} />
              {expanded ? 'Collapse' : 'Expand'}
            </button>
          )}
        </div>
      </div>

      {editing ? (
        <textarea
          className="gh-yaml-area mono"
          value={draft}
          spellCheck={false}
          onChange={(e) => setDraft(e.target.value)}
          rows={Math.min(Math.max(lines.length + 1, 16), 38)}
        />
      ) : (
        <div className={`gh-yaml-body mono ${showCollapse ? 'is-collapsed' : ''}`.trim()}>
          {lines.map((l, i) => (
            <div className="gh-yaml-line" key={i}>
              <span className="gh-yaml-gutter">{i + 1}</span>
              <code className="gh-yaml-code">{renderYaml(l, i)}</code>
            </div>
          ))}
          {showCollapse && (
            <button type="button" className="gh-yaml-expand" onClick={() => setExpanded(true)}>
              <i className="fa-solid fa-chevron-down me-2" />
              Show all {lines.length} lines
            </button>
          )}
        </div>
      )}

      <div className="gh-yaml-foot">
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
          !readOnly && (
            <>
              <button
                type="button"
                className="boc btn px-3 py-2 code-action code-action-danger"
                onClick={() => onReject?.()}
              >
                <i className="fa-solid fa-xmark me-2" />Reject
              </button>
              <button
                type="button"
                className="boc btn px-3 py-2 code-action"
                onClick={() => setEditing(true)}
              >
                <i className="fa-solid fa-pen me-2" />Edit
              </button>
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
          )
        )}
      </div>
    </div>
  );
}
