import { useCallback, useEffect, useRef, useState } from 'react';
import { terraformValidateWsUrl } from '@/services/api/workflowApi';

/* Backend LogLevel → the CSS level class used by .log-line (app.css). Identical
   to the Docker build console mapping — Terraform validation streams over the
   SAME protocol/frames ({type:'log', level, message, is_replay}). */
function normLevel(level) {
  const l = String(level || 'info').toLowerCase();
  if (l === 'warning') return 'warn';
  if (['cmd', 'info', 'warn', 'error', 'success'].includes(l)) return l;
  if (l === 'debug') return 'info';
  return 'info';
}

/** Shape one streamed/replayed entry into a console line. */
function toLine(entry, { replay = false } = {}) {
  return {
    level: normLevel(entry.level),
    text: entry.message ?? entry.text ?? '',
    ts: entry.timestamp || null,
    isReplay: replay || !!entry.is_replay,
  };
}

const MAX_RECONNECTS = 5;
const PING_MS = 20000;

/**
 * useTerraformValidation — owns the LIVE Terraform-validation log experience for
 * ONE task, over the real WebSocket `WS /ws/terraform/:taskId/terraform_validate`.
 * This reuses the EXACT streaming protocol of the Docker build socket
 * (log / complete / error / info / pong, history replayed on connect), so the
 * message handling mirrors useDockerBuild. It does NOT own the authoritative
 * phase status — that is read from `phases_state.TERRAFORM_VALIDATION` by the
 * page; this hook only drives the console + signals completion so the page can
 * refetch the workflow + the validation report.
 *
 *   • logs            terminal lines streamed over the socket. The backend
 *                     replays buffered history first, so we reset logs on open.
 *   • status          live stream state: idle | running | success | failed.
 *   • connectionState idle | connecting | open | reconnecting | closed | error
 *   • connect(taskId) attach the socket for a task (after POST or on resume).
 *
 * Unlike useDockerBuild there is no separate status endpoint to hydrate from:
 * the task_id is only known at connect time (from the phase-run response or,
 * on resume, parsed from the phase's stream_key), and the persisted outcome
 * lives in phases_state + the validation_report artifact.
 *
 * Reconnect policy: the hook reconnects ONLY while the AUTHORITATIVE phase status
 * (`phases_state.TERRAFORM_VALIDATION`, passed in as `phaseStatus`) is "running"
 * — never on the basis of the ephemeral WS status — so a settled phase can never
 * reconnect-storm. Logs are NOT wiped on reconnect: the backend replays full
 * history on every connect, so each connection rebuilds its view in a buffer that
 * is swapped in as frames arrive; a failed/empty reconnect preserves what's shown.
 *
 * @param {{ onComplete?: (finalStatus: 'success'|'failed') => void,
 *           phaseStatus?: string }} [opts]
 */
export function useTerraformValidation(opts = {}) {
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState('idle'); // idle | running | success | failed
  const [connectionState, setConnectionState] = useState('idle');
  const [exitCode, setExitCode] = useState(null);

  const wsRef = useRef(null);
  const pingRef = useRef(null);
  const reconnectRef = useRef(null);
  const attemptsRef = useRef(0);
  const intentionalRef = useRef(false);
  const taskIdRef = useRef(null);
  // The AUTHORITATIVE phase status (phases_state.TERRAFORM_VALIDATION). Reconnect
  // decisions read THIS ref, never the ephemeral WS `status`.
  const phaseStatusRef = useRef(opts.phaseStatus);
  // Per-connection log buffer (see reconnect policy above).
  const connLogsRef = useRef([]);
  const onCompleteRef = useRef(opts.onComplete);

  useEffect(() => { phaseStatusRef.current = opts.phaseStatus; }, [opts.phaseStatus]);
  useEffect(() => { onCompleteRef.current = opts.onComplete; }, [opts.onComplete]);

  const clearTimers = useCallback(() => {
    if (pingRef.current) { clearInterval(pingRef.current); pingRef.current = null; }
    if (reconnectRef.current) { clearTimeout(reconnectRef.current); reconnectRef.current = null; }
  }, []);

  const disconnect = useCallback(() => {
    intentionalRef.current = true;
    clearTimers();
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      try { ws.send(JSON.stringify({ type: 'close' })); } catch { /* ignore */ }
      try { ws.close(); } catch { /* ignore */ }
    }
  }, [clearTimers]);

  const connect = useCallback((taskId) => {
    const id = taskId || taskIdRef.current;
    if (!id) return;
    taskIdRef.current = id;

    // Tear down any prior socket without firing reconnect logic.
    intentionalRef.current = true;
    clearTimers();
    if (wsRef.current) { try { wsRef.current.close(); } catch { /* ignore */ } }
    intentionalRef.current = false;

    setStatus((s) => (s === 'success' || s === 'failed' ? 'running' : s === 'idle' ? 'running' : s));
    setExitCode(null);
    setConnectionState((s) => (s === 'reconnecting' ? s : 'connecting'));

    let ws;
    try {
      ws = new WebSocket(terraformValidateWsUrl(id));
    } catch {
      setConnectionState('error');
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      attemptsRef.current = 0;
      setConnectionState('open');
      // Do NOT wipe displayed logs. The backend replays full history on connect,
      // so we rebuild THIS connection's view in connLogsRef and swap it into
      // `logs` as frames arrive — a failed/empty reconnect preserves what's shown.
      connLogsRef.current = [];
      setStatus('running');
      pingRef.current = setInterval(() => {
        try { ws.send(JSON.stringify({ type: 'ping' })); } catch { /* ignore */ }
      }, PING_MS);
    };

    const pushLine = (line) => {
      connLogsRef.current = [...connLogsRef.current, line];
      setLogs(connLogsRef.current);
    };

    ws.onmessage = (evt) => {
      let msg;
      try { msg = JSON.parse(evt.data); } catch { return; }
      switch (msg.type) {
        case 'log':
          pushLine(toLine(msg));
          break;
        case 'complete': {
          const final = msg.status === 'success' ? 'success' : 'failed';
          setStatus(final);
          if (msg.exit_code != null) setExitCode(msg.exit_code);
          intentionalRef.current = true;
          clearTimers();
          setConnectionState('closed');
          try { ws.close(); } catch { /* ignore */ }
          onCompleteRef.current?.(final);
          break;
        }
        case 'error':
          pushLine({ level: 'error', text: msg.message || 'Stream error', ts: null });
          setConnectionState('error');
          break;
        case 'info':
          pushLine({ level: 'info', text: msg.message || '', ts: null });
          break;
        case 'pong':
        default:
          break;
      }
    };

    ws.onerror = () => {
      setConnectionState((s) => (s === 'open' ? 'error' : s));
    };

    ws.onclose = () => {
      clearTimers();
      if (intentionalRef.current) return;
      // Reconnect ONLY while the AUTHORITATIVE phase is still running — never on
      // the ephemeral WS status — so a settled phase can't reconnect-storm.
      if (phaseStatusRef.current === 'running' && attemptsRef.current < MAX_RECONNECTS) {
        attemptsRef.current += 1;
        setConnectionState('reconnecting');
        const delay = Math.min(1000 * 2 ** (attemptsRef.current - 1), 8000);
        reconnectRef.current = setTimeout(() => connect(id), delay);
      } else {
        setConnectionState('closed');
      }
    };
  }, [clearTimers]);

  /** Manually re-attach the socket (the console's "Reconnect" affordance). */
  const reconnect = useCallback(() => {
    attemptsRef.current = 0;
    connect(taskIdRef.current);
  }, [connect]);

  // Tidy the socket on unmount.
  useEffect(() => () => disconnect(), [disconnect]);

  return {
    logs,
    status,
    connectionState,
    exitCode,
    running: status === 'running',
    connect,
    reconnect,
    disconnect,
  };
}

export default useTerraformValidation;
