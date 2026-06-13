import { Fragment, useState } from 'react';
import TerraformFileTabs from './TerraformFileTabs';

/**
 * TerraformFileViewer — read-only, syntax-highlighted viewer for the generated
 * Terraform files with tab switching. Lightweight HCL highlighter (no external
 * dependency).
 *
 * Props:
 *  - files: [{ name, content, lines, summary }]
 *  - active / onSelect: optional controlled active file; otherwise internal.
 */

const HCL_KEYWORDS = new Set([
  'resource', 'variable', 'output', 'provider', 'terraform', 'module', 'data',
  'locals', 'required_providers', 'required_version', 'backend', 'source', 'version',
]);
const HCL_BUILTINS = new Set(['true', 'false', 'null', 'var', 'local', 'count', 'each']);

/** Highlight one HCL line into inline colored token spans. */
function renderHcl(line) {
  if (/^\s*(#|\/\/)/.test(line)) {
    return <span className="tok-comment">{line || ' '}</span>;
  }
  const segs = line.split(/("(?:[^"\\]|\\.)*")/g);
  return segs.map((seg, i) => {
    if (seg.startsWith('"') && seg.endsWith('"')) {
      return <span className="tok-str" key={i}>{seg}</span>;
    }
    const words = seg.split(/(\b\w+\b)/g);
    return (
      <Fragment key={i}>
        {words.map((w, j) => {
          const k = `${i}-${j}`;
          if (HCL_KEYWORDS.has(w)) return <span className="tok-instr" key={k}>{w}</span>;
          if (HCL_BUILTINS.has(w)) return <span className="tok-kw" key={k}>{w}</span>;
          if (/^\d[\d.]*$/.test(w)) return <span className="tok-num" key={k}>{w}</span>;
          return <Fragment key={k}>{w}</Fragment>;
        })}
      </Fragment>
    );
  });
}

export default function TerraformFileViewer({ files = [], active, onSelect }) {
  const [internal, setInternal] = useState(files[0]?.name);
  const activeName = active ?? internal;
  const current = files.find((f) => f.name === activeName) || files[0];
  const select = onSelect || setInternal;

  if (!current) return null;
  const lines = current.content.replace(/\n$/, '').split('\n');

  return (
    <div className="tf-viewer">
      <TerraformFileTabs files={files} active={current.name} onSelect={select} />
      <div className="tf-viewer-bar">
        <span className="mono">{current.name}</span>
        <span className="text-muted-3">
          {current.summary} · {current.lines} lines
        </span>
      </div>
      <div className="tf-code mono">
        {lines.map((l, i) => (
          <div className="tf-codeline" key={i}>
            <span className="tf-gutter">{i + 1}</span>
            <code className="tf-codetext">{renderHcl(l)}</code>
          </div>
        ))}
      </div>
    </div>
  );
}
