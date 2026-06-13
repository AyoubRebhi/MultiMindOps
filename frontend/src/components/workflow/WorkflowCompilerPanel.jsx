import { useState } from 'react';
import { formatDate } from '@/utils/formatters';

/**
 * WorkflowCompilerPanel — the Workflow Compiler (Section 8). Shows the
 * compilation status, the workflow checksum, the actions pinned to immutable
 * SHAs and the generated workflow.lock file (copy / download).
 *
 * Props:
 *  - status: 'not_started' | 'compiling' | 'compiled'
 *  - result: compilation result (see mockCompilationResults) or null
 */
export default function WorkflowCompilerPanel({ status = 'not_started', result = null }) {
  const [copied, setCopied] = useState(false);

  if (status === 'compiling' || (status !== 'compiled' && !result)) {
    return (
      <div className="compiler-busy">
        <i className="fa-solid fa-gears fa-spin" />
        <span>Pinning actions, computing checksum and emitting workflow.lock…</span>
      </div>
    );
  }
  if (!result) return null;

  const copyLock = async () => {
    try {
      await navigator.clipboard.writeText(result.lockFile);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — no-op */
    }
  };
  const downloadLock = () => {
    const blob = new Blob([result.lockFile], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'workflow.lock';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="compiler-panel">
      {/* Compilation status metrics */}
      <div className="build-metrics">
        <Metric icon="fa-circle-check" label="Compilation Status" value="Compiled" tone="#34d399" />
        <Metric icon="fa-thumbtack" label="Pinned Actions" value={result.pinnedActionsCount} />
        <Metric icon="fa-stopwatch" label="Duration" value={`${(result.durationMs / 1000).toFixed(2)}s`} />
        <Metric icon="fa-calendar-check" label="Compiled At" value={formatDate(result.compiledAt)} />
      </div>

      {/* Checksum */}
      <div className="compiler-checksum">
        <span className="compiler-checksum-label">
          <i className="fa-solid fa-fingerprint me-2" style={{ color: '#a78bfa' }} />
          Workflow Checksum
        </span>
        <code className="compiler-checksum-val mono">{result.checksum}</code>
      </div>

      {/* Pinned actions */}
      <div className="reasoning-label mt-3">
        <i className="fa-solid fa-thumbtack me-2" style={{ color: '#60a5fa' }} />
        Pinned Actions
      </div>
      <div className="pinned-table">
        <div className="pinned-row pinned-header">
          <span>Action</span>
          <span>Version</span>
          <span>Pinned SHA</span>
        </div>
        {result.pinnedActions.map((a) => (
          <div className="pinned-row" key={a.action}>
            <span className="mono pinned-action">{a.action}</span>
            <span><span className="tag mono">{a.version}</span></span>
            <span className="mono pinned-sha">{a.sha}</span>
          </div>
        ))}
      </div>

      {/* workflow.lock */}
      <div className="d-flex align-items-center justify-content-between mt-3 mb-2">
        <div className="reasoning-label mb-0">
          <i className="fa-solid fa-lock me-2" style={{ color: '#34d399' }} />
          workflow.lock
        </div>
        <div className="gh-yaml-tools">
          <button type="button" className="gh-tool-btn" onClick={copyLock}>
            <i className={`fa-solid ${copied ? 'fa-check' : 'fa-copy'} me-1`} />
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button type="button" className="gh-tool-btn" onClick={downloadLock}>
            <i className="fa-solid fa-download me-1" />Download
          </button>
        </div>
      </div>
      <pre className="code-block lock-block">{result.lockFile}</pre>
    </div>
  );
}

function Metric({ icon, label, value, tone }) {
  return (
    <div className="build-metric">
      <div className="build-metric-ico">
        <i className={`fa-solid ${icon}`} style={tone ? { color: tone } : undefined} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div className="build-metric-label">{label}</div>
        <div className="build-metric-value">{value}</div>
      </div>
    </div>
  );
}
