import { useEffect, useRef } from 'react';

/**
 * TerraformValidationConsole — a REAL terminal that renders the live Terraform
 * validation log stream delivered over the WebSocket
 * (WS /ws/terraform/:taskId/terraform_validate). It is a sibling of
 * DockerBuildConsole: same `.log-viewer` markup/CSS and the same WS log-frame
 * shape, just phase-appropriate labelling (no image tag, "Validation
 * passed/failed"). No new log system — it reuses the existing log-viewer
 * primitives and opens no timers; every row is a frame the backend pushed.
 *
 * Props:
 *  - logs            [{ level, text, ts, isReplay }] streamed/replayed entries
 *  - status          live stream state (idle|running|success|failed)
 *  - connectionState idle|connecting|open|reconnecting|closed|error
 *  - exitCode        final process exit code (shown once finished)
 *  - onReconnect     re-attach the socket
 *  - title           pane title (default "terraform validate")
 */
const CONN_META = {
  idle: { label: 'Idle', cls: 'log-state-idle', color: 'var(--tx3)', icon: 'fa-circle' },
  connecting: { label: 'Connecting…', cls: 'log-state-streaming', color: '#60a5fa', icon: 'fa-spinner fa-spin' },
  open: { label: 'Live', cls: 'log-state-streaming', color: '#34d399', icon: 'fa-circle' },
  reconnecting: { label: 'Reconnecting…', cls: 'log-state-paused', color: '#fbbf24', icon: 'fa-spinner fa-spin' },
  closed: { label: 'Disconnected', cls: 'log-state-idle', color: 'var(--tx3)', icon: 'fa-plug-circle-xmark' },
  error: { label: 'Connection error', cls: 'log-state-error', color: '#f87171', icon: 'fa-triangle-exclamation' },
};

const STATUS_META = {
  running: { label: 'Validating', color: '#60a5fa', icon: 'fa-spinner fa-spin' },
  success: { label: 'Passed', color: '#34d399', icon: 'fa-circle-check' },
  failed: { label: 'Failed', color: '#f87171', icon: 'fa-circle-xmark' },
  idle: { label: 'Idle', color: 'var(--tx3)', icon: 'fa-circle' },
};

export default function TerraformValidationConsole({
  logs = [],
  status = 'idle',
  connectionState = 'idle',
  exitCode = null,
  onReconnect,
  title = 'terraform validate',
}) {
  const bodyRef = useRef(null);
  const stickRef = useRef(true); // auto-scroll only while the user is at the bottom

  useEffect(() => {
    const el = bodyRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [logs]);

  const onScroll = () => {
    const el = bodyRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  };

  const conn = CONN_META[connectionState] || CONN_META.idle;
  const st = STATUS_META[status] || STATUS_META.idle;
  const finished = status === 'success' || status === 'failed';
  const showReconnect =
    typeof onReconnect === 'function' &&
    status === 'running' &&
    (connectionState === 'closed' || connectionState === 'error');

  return (
    <div className="log-viewer">
      <div className="log-toolbar">
        <div className="d-flex align-items-center gap-2" style={{ minWidth: 0 }}>
          <span className="log-dots" aria-hidden>
            <span /><span /><span />
          </span>
          <span className="log-title">{title}</span>
          <span className="log-state" style={{ color: st.color }}>
            <i className={`fa-solid ${st.icon} me-1`} />
            {st.label}
          </span>
        </div>
        <div className="d-flex align-items-center gap-2">
          <span className={`log-state ${conn.cls}`} style={{ color: conn.color }}>
            <i className={`fa-solid ${conn.icon} me-1`} />
            {conn.label}
          </span>
          {showReconnect && (
            <button type="button" className="log-btn" onClick={onReconnect}>
              <i className="fa-solid fa-rotate-right me-1" />Reconnect
            </button>
          )}
        </div>
      </div>

      <div className="log-body mono" ref={bodyRef} onScroll={onScroll}>
        {logs.length === 0 ? (
          <div className="log-empty">
            {status === 'running'
              ? 'Waiting for terraform to emit output…'
              : 'Validation output will stream here when validation starts.'}
          </div>
        ) : (
          logs.map((l, i) => (
            <div key={i} className={`log-line level-${l.level}`}>
              <span className="log-gutter">{String(i + 1).padStart(2, '0')}</span>
              <span className="log-text">
                {l.isReplay && <span style={{ color: 'var(--tx3)' }}>↺ </span>}
                {l.text}
              </span>
            </div>
          ))
        )}
        {status === 'running' && connectionState === 'open' && (
          <div className="log-line">
            <span className="log-gutter" />
            <span className="log-cursor" />
          </div>
        )}
      </div>

      {finished && (
        <div
          className="d-flex align-items-center gap-3 flex-wrap"
          style={{ padding: '8px 14px', borderTop: '1px solid var(--bd)', fontSize: '.78rem' }}
        >
          <span style={{ color: status === 'success' ? '#34d399' : '#f87171' }}>
            <i className={`fa-solid ${status === 'success' ? 'fa-circle-check' : 'fa-circle-xmark'} me-2`} />
            Validation {status === 'success' ? 'passed' : 'failed'}
          </span>
          {exitCode != null && (
            <span style={{ color: 'var(--tx3)' }}>exit code {exitCode}</span>
          )}
        </div>
      )}
    </div>
  );
}
