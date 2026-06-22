import { useNavigate } from 'react-router-dom';
import {
  WORKFLOW_TIMELINE_PHASES,
  deriveTimelineStatuses,
} from '@/utils/constants';

/**
 * WorkflowTimeline — the reusable, top-center pipeline indicator shown on every
 * workflow phase page. Renders the ordered phases (Analysis → Planning → Docker
 * → Terraform → Validation → Plan) with per-phase state.
 *
 * Supported states: not_started · running · completed · cancelled · failed.
 *
 * Props:
 *  - current: phase key of the active page (e.g. "planning"). When `statuses`
 *    is omitted, states are derived from this (earlier = completed, current =
 *    running, later = not_started).
 *  - statuses: optional { key: state } map to override the derived states
 *    (e.g. mark the current phase completed/failed once its work finishes).
 *  - phases: optional phase list (defaults to WORKFLOW_TIMELINE_PHASES).
 *  - navigable: allow clicking reached (completed/running) phases to navigate.
 */
const NODE_STATE = {
  completed: { cls: 'is-done', icon: 'fa-check' },
  running: { cls: 'is-running', icon: 'fa-spinner fa-spin' },
  // Phase 3A — operator-stopped phase: neutral "ban" glyph, between running and
  // failed (it is not an error). Reuses the failed node styling for visibility.
  cancelled: { cls: 'is-failed', icon: 'fa-ban' },
  failed: { cls: 'is-failed', icon: 'fa-xmark' },
  not_started: { cls: '', icon: null },
};

export default function WorkflowTimeline({
  current,
  statuses,
  phases = WORKFLOW_TIMELINE_PHASES,
  navigable = true,
}) {
  const navigate = useNavigate();
  const states = statuses || deriveTimelineStatuses(current);

  return (
    <div className="wf-timeline-wrap">
      <div className="wf-timeline" role="list" aria-label="Workflow progress">
        {phases.map((phase) => {
          const state = states[phase.key] || 'not_started';
          const node = NODE_STATE[state] || NODE_STATE.not_started;
          const isCurrent = phase.key === current;
          const reached =
            state === 'completed' ||
            state === 'running' ||
            state === 'failed' ||
            state === 'cancelled';
          const canNavigate = navigable && reached && phase.to && !isCurrent;

          return (
            <div
              key={phase.key}
              role="listitem"
              className={`wf-step ${reached ? 'is-reached' : ''} ${
                isCurrent ? 'is-current' : ''
              }`.trim()}
            >
              <button
                type="button"
                className={`wf-step-node ${node.cls}`.trim()}
                disabled={!canNavigate}
                onClick={canNavigate ? () => navigate(phase.to) : undefined}
                style={{ cursor: canNavigate ? 'pointer' : 'default' }}
                aria-current={isCurrent ? 'step' : undefined}
                title={phase.label}
              >
                {node.icon ? (
                  <i className={`fa-solid ${node.icon}`} />
                ) : (
                  <i
                    className={`${phase.brand ? 'fa-brands' : 'fa-solid'} ${phase.icon}`}
                    style={{ opacity: 0.65 }}
                  />
                )}
              </button>
              <div className={`wf-step-label ${isCurrent ? 'is-current' : ''}`.trim()}>
                {phase.label}
              </div>
              <div className="wf-step-state">
                {state === 'not_started' ? '—' : state.replace('_', ' ')}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
