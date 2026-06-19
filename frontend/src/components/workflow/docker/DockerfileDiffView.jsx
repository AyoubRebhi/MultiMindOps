import { useMemo } from 'react';

/**
 * DockerfileDiffView — lightweight side-by-side diff of the original vs the
 * corrected Dockerfile. Uses a small line-level LCS (Dockerfiles are tiny) to
 * align unchanged lines and highlight removals (left, red) and additions
 * (right, green) so an engineer can see exactly WHAT changed.
 *
 * Props:
 *  - original   originally generated Dockerfile text
 *  - corrected  corrected Dockerfile text
 */
function diffLines(aText, bText) {
  const a = aText.split('\n');
  const b = bText.split('\n');
  const n = a.length;
  const m = b.length;

  // LCS length table.
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  // Backtrack into aligned rows.
  const rows = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({ type: 'same', left: a[i], right: b[j], ln: i + 1, rn: j + 1 });
      i++; j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ type: 'remove', left: a[i], right: null, ln: i + 1, rn: null });
      i++;
    } else {
      rows.push({ type: 'add', left: null, right: b[j], ln: null, rn: j + 1 });
      j++;
    }
  }
  while (i < n) rows.push({ type: 'remove', left: a[i], right: null, ln: ++i, rn: null });
  while (j < m) rows.push({ type: 'add', left: null, right: b[j], ln: null, rn: ++j });
  return rows;
}

function Side({ rows, side, leftLabel, rightLabel }) {
  const isLeft = side === 'left';
  return (
    <div style={{ flex: 1, minWidth: 0, overflow: 'auto' }}>
      <div
        style={{
          padding: '8px 12px',
          borderBottom: '1px solid var(--bd)',
          fontSize: '.76rem',
          fontWeight: 600,
          color: 'var(--tx2)',
          position: 'sticky',
          top: 0,
          background: 'var(--bg2, var(--bg))',
        }}
      >
        <i className={`fa-solid ${isLeft ? 'fa-file-circle-minus' : 'fa-file-circle-check'} me-2`}
           style={{ color: isLeft ? '#f87171' : '#34d399' }} />
        {isLeft ? leftLabel : rightLabel}
      </div>
      <pre style={{ margin: 0, padding: '6px 0', fontSize: '.76rem', lineHeight: 1.5 }}>
        {rows.map((r, idx) => {
          const text = isLeft ? r.left : r.right;
          const num = isLeft ? r.ln : r.rn;
          const present = text !== null;
          const changed = isLeft ? r.type === 'remove' : r.type === 'add';
          const bg = !present
            ? 'transparent'
            : changed
            ? isLeft
              ? 'rgba(248,113,113,.14)'
              : 'rgba(52,211,153,.14)'
            : 'transparent';
          const mark = isLeft ? '-' : '+';
          return (
            <div key={idx} style={{ display: 'flex', background: bg, minHeight: '1.2em' }}>
              <span aria-hidden style={{ width: 36, flexShrink: 0, textAlign: 'right', paddingRight: 8, color: 'var(--tx3)', userSelect: 'none' }}>
                {num ?? ''}
              </span>
              <span aria-hidden style={{ width: 14, flexShrink: 0, color: changed ? (isLeft ? '#f87171' : '#34d399') : 'transparent', userSelect: 'none' }}>
                {present && changed ? mark : ''}
              </span>
              <code style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {present ? text || ' ' : ''}
              </code>
            </div>
          );
        })}
      </pre>
    </div>
  );
}

export default function DockerfileDiffView({
  original = '',
  corrected = '',
  leftLabel = 'Original Dockerfile',
  rightLabel = 'Corrected Dockerfile',
}) {
  const rows = useMemo(() => diffLines(original, corrected), [original, corrected]);
  const added = rows.filter((r) => r.type === 'add').length;
  const removed = rows.filter((r) => r.type === 'remove').length;

  return (
    <div className="surface" style={{ padding: 0, overflow: 'hidden' }}>
      <div className="d-flex align-items-center gap-3 flex-wrap" style={{ padding: '10px 14px', borderBottom: '1px solid var(--bd)' }}>
        <span style={{ fontWeight: 600, fontSize: '.85rem' }}>
          <i className="fa-solid fa-code-compare me-2" style={{ color: 'var(--tx3)' }} />
          Change comparison
        </span>
        <span className="badge-pill badge-success" style={{ fontSize: '.72rem' }}>+{added} added</span>
        <span className="badge-pill badge-danger" style={{ fontSize: '.72rem' }}>−{removed} removed</span>
      </div>
      <div className="d-flex" style={{ maxHeight: 460 }}>
        <Side rows={rows} side="left" leftLabel={leftLabel} rightLabel={rightLabel} />
        <div style={{ width: 1, background: 'var(--bd)', flexShrink: 0 }} />
        <Side rows={rows} side="right" leftLabel={leftLabel} rightLabel={rightLabel} />
      </div>
    </div>
  );
}
