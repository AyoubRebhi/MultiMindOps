import { useEffect, useRef, useState } from 'react';

/**
 * PipelineGraph — a visual DAG of the pipeline (Section 2 of the Execution
 * Center). Nodes flow top-to-bottom (Checkout → Build → … → Health Checks) and
 * animate live when the parent bumps `runKey`: the current node pulses while
 * completed nodes turn green. If `failIndex >= 0` the matching node fails and
 * the run stops there; otherwise every node succeeds.
 *
 * The animation is self-contained (its own timers, cleaned up on unmount) so it
 * stays in step regardless of the log stream. It calls `onDone(outcome)` once it
 * settles. No real DAG engine — purely presentational.
 *
 * Props:
 *  - nodes: [{ key, label, icon, brand, duration, logs, artifacts }]
 *  - runKey: number — each new value > 0 (re)starts the animation
 *  - failIndex: number — node index to fail at, or -1 for a full success
 *  - onDone(outcome: 'completed' | 'failed')
 *  - stepMs: per-node dwell time (default 780)
 */
const NODE_META = {
  pending: { cls: 'is-pending', icon: 'fa-clock' },
  running: { cls: 'is-running', icon: 'fa-spinner fa-spin' },
  success: { cls: 'is-success', icon: 'fa-check' },
  failed: { cls: 'is-failed', icon: 'fa-xmark' },
};

export default function PipelineGraph({
  nodes = [],
  runKey = 0,
  failIndex = -1,
  onDone,
  stepMs = 780,
}) {
  const [states, setStates] = useState(() => nodes.map(() => 'pending'));

  const timerRef = useRef(null);
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  // (Re)start the animation whenever the parent bumps runKey.
  useEffect(() => {
    if (runKey <= 0 || nodes.length === 0) return undefined;
    clearTimer();

    const next = nodes.map(() => 'pending');
    next[0] = 'running';
    setStates(next);

    let idx = 0;
    const tick = () => {
      const delay = stepMs + Math.random() * 320;
      timerRef.current = setTimeout(() => {
        setStates((prev) => {
          const copy = [...prev];
          if (idx === failIndex) {
            copy[idx] = 'failed';
            return copy;
          }
          copy[idx] = 'success';
          if (idx + 1 < nodes.length) copy[idx + 1] = 'running';
          return copy;
        });

        if (idx === failIndex) {
          clearTimer();
          onDoneRef.current?.('failed');
          return;
        }
        idx += 1;
        if (idx < nodes.length) {
          tick();
        } else {
          clearTimer();
          onDoneRef.current?.('completed');
        }
      }, delay);
    };
    tick();

    return clearTimer;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runKey]);

  // Tidy on unmount.
  useEffect(() => () => clearTimer(), []);

  return (
    <div className="pg-graph">
      {nodes.map((node, i) => {
        const state = states[i] || 'pending';
        const meta = NODE_META[state] || NODE_META.pending;
        const showStats = state === 'success' || state === 'failed';
        return (
          <div className="pg-step" key={node.key}>
            <div className={`pg-node ${meta.cls}`}>
              <span className="pg-node-ico">
                <i className={`${node.brand ? 'fa-brands' : 'fa-solid'} ${node.icon}`} />
              </span>
              <div className="pg-node-body">
                <div className="pg-node-label">{node.label}</div>
                <div className="pg-node-meta">
                  {showStats && node.duration && (
                    <span className="pg-chip">
                      <i className="fa-solid fa-stopwatch" />{node.duration}
                    </span>
                  )}
                  {node.logs && (
                    <span className="pg-chip">
                      <i className="fa-solid fa-terminal" />logs
                    </span>
                  )}
                  {node.artifacts > 0 && (
                    <span className="pg-chip">
                      <i className="fa-solid fa-box-archive" />
                      {node.artifacts} {node.artifacts === 1 ? 'artifact' : 'artifacts'}
                    </span>
                  )}
                </div>
              </div>
              <span className={`pg-node-state ${meta.cls}`}>
                <i className={`fa-solid ${meta.icon}`} />
              </span>
            </div>
            {i < nodes.length - 1 && (
              <div className={`pg-edge ${state === 'success' ? 'is-flowed' : ''}`.trim()}>
                <i className="fa-solid fa-arrow-down" />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
