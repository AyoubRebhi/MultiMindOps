import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * RealtimeLogViewer — a reusable, terminal-style log pane that *simulates* a
 * websocket build feed by replaying an array of `{ level, text }` events
 * line-by-line with a little timing jitter. No real socket is opened.
 *
 * Controls: Start Build · Pause/Resume · Clear Logs.
 *
 * Coordination with the parent:
 *  - `onStart()`   fires when the user clicks Start (the parent typically marks
 *                  the build running, fetches the right script, then bumps
 *                  `playKey` to begin streaming).
 *  - `playKey`     a number; each time it *changes to a new value > 0* the
 *                  viewer (re)starts streaming the current `events` from line 1.
 *  - `onComplete()`fires once the last line has streamed.
 *
 * Props:
 *  - events: [{ level: 'info'|'cmd'|'warn'|'error'|'success', text }]
 *  - playKey, onStart, onComplete
 *  - canStart: enable the Start button (default true)
 *  - preparing: show a brief "Preparing…" state on the Start button
 *  - title: pane title (default "Build Output")
 *  - emptyHint: text shown before the first run
 *  - startLabel: label for the primary button (default "Start Build"); lets the
 *    same viewer read as "Run Validation" / "Retry Execution" etc.
 *  - searchable: show a "Search logs" input that filters the displayed lines
 *    (purely visual — streaming continues underneath). Default false so other
 *    phases are unaffected.
 */
export default function RealtimeLogViewer({
  events = [],
  playKey = 0,
  onStart,
  onComplete,
  canStart = true,
  preparing = false,
  title = 'Build Output',
  emptyHint = 'Logs will stream here once the build starts.',
  startLabel = 'Start Build',
  searchable = false,
}) {
  const [lines, setLines] = useState([]);
  const [phase, setPhase] = useState('idle'); // idle | streaming | paused | done
  const [search, setSearch] = useState('');

  const timerRef = useRef(null);
  const idxRef = useRef(0);
  const eventsRef = useRef(events);
  const onCompleteRef = useRef(onComplete);
  const bodyRef = useRef(null);

  useEffect(() => {
    eventsRef.current = events;
  }, [events]);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const scheduleNext = useCallback(() => {
    const ev = eventsRef.current || [];
    if (idxRef.current >= ev.length) {
      clearTimer();
      setPhase('done');
      onCompleteRef.current?.();
      return;
    }
    const item = ev[idxRef.current];
    // errors linger a touch longer; otherwise gentle jitter for a "live" feel
    const delay = (item?.level === 'error' ? 460 : 300) + Math.random() * 280;
    timerRef.current = setTimeout(() => {
      idxRef.current += 1;
      setLines((prev) => [...prev, item]);
      scheduleNext();
    }, delay);
  }, []);

  const beginStream = useCallback(() => {
    clearTimer();
    idxRef.current = 0;
    setLines([]);
    setPhase('streaming');
    scheduleNext();
  }, [scheduleNext]);

  // Restart streaming whenever the parent bumps playKey.
  useEffect(() => {
    if (playKey > 0) beginStream();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playKey]);

  // Tidy the timer on unmount.
  useEffect(() => () => clearTimer(), []);

  // Keep the newest line in view.
  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines, phase]);

  const handlePauseResume = () => {
    if (phase === 'streaming') {
      clearTimer();
      setPhase('paused');
    } else if (phase === 'paused') {
      setPhase('streaming');
      scheduleNext();
    }
  };

  const handleClear = () => {
    clearTimer();
    idxRef.current = 0;
    setLines([]);
    setPhase('idle');
  };

  const streaming = phase === 'streaming';
  const startDisabled = !canStart || streaming || preparing;

  return (
    <div className="log-viewer">
      <div className="log-toolbar">
        <div className="d-flex align-items-center gap-2" style={{ minWidth: 0 }}>
          <span className="log-dots" aria-hidden>
            <span /><span /><span />
          </span>
          <span className="log-title">{title}</span>
          <span className={`log-state log-state-${phase}`}>
            {streaming && <i className="fa-solid fa-spinner fa-spin me-1" />}
            {phase === 'idle' && 'idle'}
            {phase === 'streaming' && 'streaming'}
            {phase === 'paused' && 'paused'}
            {phase === 'done' && 'finished'}
          </span>
        </div>
        <div className="d-flex align-items-center gap-2">
          {searchable && (
            <span className="log-search">
              <i className="fa-solid fa-magnifying-glass" />
              <input
                type="text"
                placeholder="Search logs…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {search && (
                <button type="button" className="log-search-clear" onClick={() => setSearch('')} aria-label="Clear search">
                  <i className="fa-solid fa-xmark" />
                </button>
              )}
            </span>
          )}
          <button
            type="button"
            className="log-btn log-btn-primary"
            disabled={startDisabled}
            onClick={() => onStart?.()}
          >
            {preparing ? (
              <><i className="fa-solid fa-spinner fa-spin me-1" />Preparing…</>
            ) : (
              <><i className="fa-solid fa-play me-1" />{startLabel}</>
            )}
          </button>
          <button
            type="button"
            className="log-btn"
            disabled={phase !== 'streaming' && phase !== 'paused'}
            onClick={handlePauseResume}
          >
            {phase === 'paused' ? (
              <><i className="fa-solid fa-play me-1" />Resume</>
            ) : (
              <><i className="fa-solid fa-pause me-1" />Pause</>
            )}
          </button>
          <button
            type="button"
            className="log-btn"
            disabled={lines.length === 0 && phase === 'idle'}
            onClick={handleClear}
          >
            <i className="fa-solid fa-trash-can me-1" />Clear
          </button>
        </div>
      </div>

      <div className="log-body mono" ref={bodyRef}>
        {lines.length === 0 ? (
          <div className="log-empty">{emptyHint}</div>
        ) : (
          (() => {
            const q = searchable ? search.trim().toLowerCase() : '';
            const shown = q
              ? lines
                  .map((l, i) => ({ l, i }))
                  .filter(({ l }) => l.text.toLowerCase().includes(q))
              : lines.map((l, i) => ({ l, i }));
            if (q && shown.length === 0) {
              return <div className="log-empty">No log lines match &ldquo;{search}&rdquo;.</div>;
            }
            return shown.map(({ l, i }) => (
              <div key={i} className={`log-line level-${l.level}`}>
                <span className="log-gutter">{String(i + 1).padStart(2, '0')}</span>
                <span className="log-text">{l.text}</span>
              </div>
            ));
          })()
        )}
        {streaming && (
          <div className="log-line">
            <span className="log-gutter" />
            <span className="log-cursor" />
          </div>
        )}
      </div>
    </div>
  );
}
