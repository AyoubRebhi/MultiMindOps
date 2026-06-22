import { useCallback, useEffect, useRef, useState } from 'react';
import { dockerBuildApi, dockerBuildWsUrl } from '@/services/api/dockerBuildApi';
import { executionControlApi } from '@/services/api/executionControlApi';

/* Backend LogLevel → the CSS level class used by .log-line (app.css). */
function normLevel(level) {
  const l = String(level || 'info').toLowerCase();
  if (l === 'warning') return 'warn';
  if (['cmd', 'info', 'warn', 'error', 'success'].includes(l)) return l;
  if (l === 'debug') return 'info';
  return 'info';
}

/** Shape one persisted/streamed entry into a console line. */
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
 * useDockerBuild — owns the live Docker build experience for ONE task:
 *
 *  • status        authoritative build state from the backend (pending | running
 *                  | success | failed | blocked) — NEVER inferred from log text.
 *  • logs          terminal lines streamed over the REAL WebSocket
 *                  (WS /ws/execution/:taskId). On (re)connect the backend replays
 *                  full history first, so we reset logs on each open to dedupe.
 *  • connectionState  idle | connecting | open | reconnecting | closed | error
 *  • start()/rebuild()  enqueue a build, then attach the socket.
 *
 * @param {string} taskId
 * @param {{ onComplete?: (finalStatus: string) => void }} [opts]
 */
export function useDockerBuild(taskId, opts = {}) {
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState('pending');
  const [connectionState, setConnectionState] = useState('idle');
  const [exitCode, setExitCode] = useState(null);
  const [imageTag, setImageTag] = useState(null);
  const [blockReason, setBlockReason] = useState(null);
  const [starting, setStarting] = useState(false);
  // Phase 3A — the active/last build job + its project, needed to address the
  // cancel endpoint. Captured from the build POST response and the status GET.
  const [jobId, setJobId] = useState(null);
  const [projectId, setProjectId] = useState(null);
  const [cancelling, setCancelling] = useState(false);

  const wsRef = useRef(null);
  const pingRef = useRef(null);
  const reconnectRef = useRef(null);
  const attemptsRef = useRef(0);
  const intentionalRef = useRef(false);
  const statusRef = useRef(status);
  const onCompleteRef = useRef(opts.onComplete);

  useEffect(() => { statusRef.current = status; }, [status]);
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

  const connect = useCallback(() => {
    if (!taskId) return;
    // Tear down any prior socket without firing reconnect logic.
    intentionalRef.current = true;
    clearTimers();
    if (wsRef.current) { try { wsRef.current.close(); } catch { /* ignore */ } }
    intentionalRef.current = false;

    setConnectionState((s) => (s === 'reconnecting' ? s : 'connecting'));

    let ws;
    try {
      ws = new WebSocket(dockerBuildWsUrl(taskId));
    } catch {
      setConnectionState('error');
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      attemptsRef.current = 0;
      setConnectionState('open');
      // Backend replays the full history on connect → reset to avoid dupes.
      setLogs([]);
      pingRef.current = setInterval(() => {
        try { ws.send(JSON.stringify({ type: 'ping' })); } catch { /* ignore */ }
      }, PING_MS);
    };

    ws.onmessage = (evt) => {
      let msg;
      try { msg = JSON.parse(evt.data); } catch { return; }
      switch (msg.type) {
        case 'log':
          setLogs((prev) => [...prev, toLine(msg)]);
          break;
        case 'complete': {
          // Phase 3A — 'cancelled' is a distinct terminal (operator stopped it),
          // never coerced to 'failed', so the UI shows a neutral stopped state.
          const final =
            msg.status === 'success'
              ? 'success'
              : msg.status === 'cancelled'
                ? 'cancelled'
                : 'failed';
          setStatus(final);
          setCancelling(false);
          if (msg.exit_code != null) setExitCode(msg.exit_code);
          intentionalRef.current = true;
          clearTimers();
          setConnectionState('closed');
          try { ws.close(); } catch { /* ignore */ }
          onCompleteRef.current?.(final);
          break;
        }
        case 'error':
          setLogs((prev) => [...prev, { level: 'error', text: msg.message || 'Stream error', ts: null }]);
          setConnectionState('error');
          break;
        case 'info':
          setLogs((prev) => [...prev, { level: 'info', text: msg.message || '', ts: null }]);
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
      // Unexpected close while the build is still running → reconnect (backoff).
      if (statusRef.current === 'running' && attemptsRef.current < MAX_RECONNECTS) {
        attemptsRef.current += 1;
        setConnectionState('reconnecting');
        const delay = Math.min(1000 * 2 ** (attemptsRef.current - 1), 8000);
        reconnectRef.current = setTimeout(() => connect(), delay);
      } else {
        setConnectionState('closed');
      }
    };
  }, [taskId, clearTimers]);

  /** Manually re-attach the socket (used by the "Reconnect" UX affordance). */
  const reconnect = useCallback(() => {
    attemptsRef.current = 0;
    connect();
  }, [connect]);

  const refetchStatus = useCallback(async () => {
    if (!taskId) return null;
    const s = await dockerBuildApi.getBuildStatus(taskId).catch(() => null);
    if (!s) return null;
    setStatus(s.status);
    setExitCode(s.exitCode);
    if (s.imageTag) setImageTag(s.imageTag);
    if (s.jobId) setJobId(s.jobId);
    if (s.projectId) setProjectId(s.projectId);
    return s;
  }, [taskId]);

  /**
   * Phase 3A — request cancellation of the running build. Flags the durable job;
   * the worker stops the docker child and the WS then emits a `cancelled`
   * complete frame. Optimistically reflects a `cancelling` state so the Stop
   * button disables and reconnect loops never fire (status is no longer
   * 'running'). No-op without a known job/project.
   */
  const cancel = useCallback(async () => {
    if (!jobId || !projectId || cancelling) return { ok: false };
    setCancelling(true);
    try {
      const res = await executionControlApi.cancelJob(projectId, jobId);
      // A pending/terminal job settles immediately to 'cancelled'; a running job
      // returns 'running' and the WS delivers the cancelled frame shortly.
      if (res?.status === 'cancelled') {
        setStatus('cancelled');
        setCancelling(false);
      } else {
        setStatus('cancelling');
      }
      return { ok: true, descriptor: res };
    } catch (e) {
      setCancelling(false);
      return { ok: false, error: e };
    }
  }, [jobId, projectId, cancelling]);

  const runBuild = useCallback(
    async (apiCall) => {
      if (!taskId || starting) return { ok: false };
      setStarting(true);
      setBlockReason(null);
      setExitCode(null);
      setStatus('running');
      try {
        const res = await apiCall();
        if (res?.image_tag) setImageTag(res.image_tag);
        if (res?.job_id) setJobId(res.job_id);
        if (res?.project_id) setProjectId(res.project_id);
        setCancelling(false);
        attemptsRef.current = 0;
        connect();
        return { ok: true, descriptor: res };
      } catch (e) {
        // 422 = pre-build validation gate blocked the build (structured reason).
        if (e?.status === 422) {
          setStatus('blocked');
          setBlockReason(e.message || 'Pre-build validation blocked the build.');
        } else {
          // 409 (wrong phase / already running) and transport errors land here.
          await refetchStatus();
          setConnectionState('idle');
        }
        return { ok: false, error: e };
      } finally {
        setStarting(false);
      }
    },
    [taskId, starting, connect, refetchStatus]
  );

  const start = useCallback(() => runBuild(() => dockerBuildApi.startBuild(taskId)), [runBuild, taskId]);
  const rebuild = useCallback(() => runBuild(() => dockerBuildApi.rebuild(taskId)), [runBuild, taskId]);

  // On mount / task change: read authoritative status, hydrate the console with
  // persisted logs, and attach the live socket only when a build is running.
  useEffect(() => {
    if (!taskId) return undefined;
    let cancelled = false;
    (async () => {
      const s = await dockerBuildApi.getBuildStatus(taskId).catch(() => null);
      if (cancelled || !s) return;
      setStatus(s.status);
      setExitCode(s.exitCode);
      if (s.imageTag) setImageTag(s.imageTag);
      if (s.jobId) setJobId(s.jobId);
      if (s.projectId) setProjectId(s.projectId);
      if (s.status === 'running') {
        connect();
      } else if (Array.isArray(s.logs) && s.logs.length) {
        setLogs(s.logs.map((e) => toLine(e, { replay: true })));
      }
    })();
    return () => {
      cancelled = true;
      disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  return {
    logs,
    status,
    connectionState,
    exitCode,
    imageTag,
    blockReason,
    starting,
    building: status === 'running',
    // Phase 3A — execution control.
    jobId,
    projectId,
    cancelling,
    cancel,
    canCancel: !!(jobId && projectId) && (status === 'running' || cancelling),
    start,
    rebuild,
    reconnect,
    refetchStatus,
    disconnect,
  };
}

export default useDockerBuild;
