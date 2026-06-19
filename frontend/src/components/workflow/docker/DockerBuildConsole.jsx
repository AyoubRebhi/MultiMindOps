import { useEffect, useRef } from 'react';
import DockerBuildStatusBadge from './DockerBuildStatusBadge';

/**
 * DockerBuildConsole — a REAL terminal that renders the live Docker build log
 * stream delivered over the WebSocket (WS /ws/execution/:taskId). Unlike the
 * simulated RealtimeLogViewer, it opens no timers and fabricates no lines: every
 * row is a frame the backend pushed. It auto-scrolls (while the user is at the
 * bottom), surfaces the live WebSocket connection state, and offers a graceful
 * Reconnect when the socket drops mid-build.
 *
 * Props:
 *  - logs            [{ level, text, ts, isReplay }] streamed/replayed entries
 *  - status          backend build status (pending|running|success|failed|blocked)
 *  - connectionState idle|connecting|open|reconnecting|closed|error
 *  - exitCode        final process exit code (shown once finished)
 *  - imageTag        built image tag (shown on success)
 *  - onReconnect     re-attach the socket
 *  - title           pane title (default "Build Logs")
 */
const CONN_META = {
  idle: { label: 'Idle', cls: 'log-state-idle', color: 'var(--tx3)', icon: 'fa-circle' },
  connecting: { label: 'Connecting…', cls: 'log-state-streaming', color: '#60a5fa', icon: 'fa-spinner fa-spin' },
  open: { label: 'Live', cls: 'log-state-streaming', color: '#34d399', icon: 'fa-circle' },
  reconnecting: { label: 'Reconnecting…', cls: 'log-state-paused', color: '#fbbf24', icon: 'fa-spinner fa-spin' },
  closed: { label: 'Disconnected', cls: 'log-state-idle', color: 'var(--tx3)', icon: 'fa-plug-circle-xmark' },
  error: { label: 'Connection error', cls: 'log-state-error', color: '#f87171', icon: 'fa-triangle-exclamation' },
};

export default function DockerBuildConsole({
  logs = [],
  status,
  connectionState = 'idle',
  exitCode = null,
  imageTag = null,
  onReconnect,
  title = 'Build Logs',
}) {
  const bodyRef = useRef(null);
  const stickRef = useRef(true); // auto-scroll only while the user is at the bottom

  // Keep the newest line in view unless the user scrolled up to read history.
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
          <DockerBuildStatusBadge status={status} />
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
              ? 'Waiting for the build to emit output…'
              : 'Build output will stream here when the build starts.'}
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
            Build {status === 'success' ? 'succeeded' : 'failed'}
          </span>
          {exitCode != null && (
            <span style={{ color: 'var(--tx3)' }}>exit code {exitCode}</span>
          )}
          {status === 'success' && imageTag && (
            <span className="tag mono" style={{ fontSize: '.72rem' }}>
              <i className="fa-solid fa-box me-1" />{imageTag}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
