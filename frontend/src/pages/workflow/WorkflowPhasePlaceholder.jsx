import { useLocation, useNavigate } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import EmptyState from '@/components/common/EmptyState';
import {
  WORKFLOW_TIMELINE_PHASES,
  getTimelineIndex,
} from '@/utils/constants';

/**
 * WorkflowPhasePlaceholder — a friendly "next iteration" screen reused for the
 * phases not yet implemented (Terraform, Validation, Plan). It keeps the
 * timeline navigable and the "Proceed to Next Phase" action from dead-ending,
 * which matters for the live PFE demo. The Planning and Docker phases are the
 * fully-built ones.
 */
export default function WorkflowPhasePlaceholder() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const phase =
    WORKFLOW_TIMELINE_PHASES.find((p) => p.to === pathname) ||
    WORKFLOW_TIMELINE_PHASES[3];

  const idx = getTimelineIndex(phase.key);
  // Everything up to (and including) the Docker phase is "done" in the demo.
  const statuses = {};
  WORKFLOW_TIMELINE_PHASES.forEach((p, i) => {
    if (i < idx) statuses[p.key] = 'completed';
    else if (i === idx) statuses[p.key] = 'running';
    else statuses[p.key] = 'not_started';
  });

  const prev = WORKFLOW_TIMELINE_PHASES[idx - 1];

  return (
    <ContentContainer>
      <WorkflowTimeline current={phase.key} statuses={statuses} />

      <WorkflowPhaseHeader
        icon={phase.icon}
        brand={phase.brand}
        eyebrow={`Phase ${idx + 1} of ${WORKFLOW_TIMELINE_PHASES.length}`}
        title={phase.label}
        subtitle="This workflow phase is coming in the next iteration."
        status="not_started"
      />

      <div className="surface">
        <EmptyState
          icon={phase.icon}
          title={`${phase.label} phase — coming soon`}
          message="The reusable workflow architecture (timeline, phase headers, status cards, log streaming and corrector pattern) is ready — this phase will plug into it next."
          action={
            <div className="d-flex gap-2 justify-content-center">
              {prev && (
                <button
                  type="button"
                  className="boc btn px-3 py-2"
                  onClick={() => navigate(prev.to)}
                >
                  <i className="fa-solid fa-arrow-left me-2" />
                  Back to {prev.label}
                </button>
              )}
              <button
                type="button"
                className="bgrd btn px-3 py-2"
                onClick={() => navigate('/workflows')}
              >
                All workflows
              </button>
            </div>
          }
        />
      </div>
    </ContentContainer>
  );
}
