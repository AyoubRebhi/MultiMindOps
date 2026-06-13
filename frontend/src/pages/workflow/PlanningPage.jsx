import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import PhaseStatusCard from '@/components/workflow/PhaseStatusCard';
import PlanSelectionCard from '@/components/workflow/PlanSelectionCard';
import ProgressBar from '@/components/common/ProgressBar';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { useAsync } from '@/hooks/useAsync';
import { planningApi } from '@/services/api/planningApi';

/**
 * PlanningPage — workflow phase 1. Shows the Planning Agent's requirements
 * analysis, then three side-by-side architecture plans to choose from. Exactly
 * one plan can be selected before proceeding to the Docker phase.
 * Route: /workflows/planning.
 */
export default function PlanningPage() {
  const navigate = useNavigate();
  const { data: planning, loading: pLoading } = useAsync(() => planningApi.getPlanning());
  const { data: plans, loading: plLoading } = useAsync(() => planningApi.listPlans(), [], {
    initialData: [],
  });

  // Pre-select the recommended plan so the page never looks empty.
  const [selectedId, setSelectedId] = useState(null);
  const recommendedId = (plans || []).find((p) => p.recommended)?.id;
  const effectiveSelected = selectedId ?? recommendedId ?? null;

  if (pLoading || !planning) {
    return (
      <ContentContainer>
        <LoadingSpinner center label="Planning agent is reasoning…" />
      </ContentContainer>
    );
  }

  return (
    <ContentContainer>
      <WorkflowTimeline current="planning" />

      <WorkflowPhaseHeader
        icon="fa-clipboard-list"
        eyebrow="Phase 1 of 6"
        title="Planning"
        subtitle="The Planning Agent sized the workload and proposed candidate architectures."
        status="running"
      />

      {/* ============ SECTION 1 — Planning Agent Result ============ */}
      <div className="section-label">
        <span className="section-label-chip">1</span>
        Planning Agent Result
        <span className="section-label-by">Planning Agent</span>
      </div>

      <div className="row g-3 mb-2">
        <div className="col-lg-7">
          <PhaseStatusCard icon="fa-list-check" title="Project Requirements Summary">
            <p className="mb-0" style={{ fontSize: '.88rem', color: 'var(--tx2)', lineHeight: 1.7 }}>
              {planning.requirementsSummary}
            </p>
            <div className="mt-3">
              <div className="d-flex align-items-center justify-content-between mb-1">
                <span className="form-label-sm mb-0">Complexity · {planning.complexity.level}</span>
                <span className="text-muted-3" style={{ fontSize: '.74rem' }}>
                  {planning.complexity.score}/100
                </span>
              </div>
              <ProgressBar value={planning.complexity.score} />
              <div className="d-flex flex-wrap gap-2 mt-2">
                {planning.complexity.drivers.map((d) => (
                  <span className="tag" key={d}>{d}</span>
                ))}
              </div>
            </div>
          </PhaseStatusCard>
        </div>

        <div className="col-lg-5">
          <div className="row g-3">
            <div className="col-sm-6 col-lg-12">
              <AssessTile data={planning.infrastructureSize} title="Expected Infrastructure Size" />
            </div>
            <div className="col-sm-6 col-lg-12">
              <AssessTile data={planning.teamScale} title="Estimated Team Scale" />
            </div>
            <div className="col-12 d-none d-lg-block">
              <AssessTile data={planning.trafficProfile} title="Traffic Profile" />
            </div>
          </div>
        </div>
      </div>

      {/* ============ SECTION 2 — Architecture Plan Selection ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">2</span>
        Architecture Plan Selection
        <span className="section-label-by">Choose one to continue</span>
      </div>

      {plLoading && !plans?.length ? (
        <LoadingSpinner center label="Loading plans…" />
      ) : (
        <div className="row g-3 align-items-stretch">
          {plans.map((plan) => (
            <div className="col-lg-4" key={plan.id}>
              <PlanSelectionCard
                plan={plan}
                selected={effectiveSelected === plan.id}
                onSelect={() => setSelectedId(plan.id)}
              />
            </div>
          ))}
        </div>
      )}

      {/* ---- Proceed ---- */}
      <div className="phase-footer">
        <p className="phase-footer-note">
          {effectiveSelected ? (
            <>
              <i className="fa-solid fa-circle-check me-2" style={{ color: '#34d399' }} />
              Selected: <strong>{plans.find((p) => p.id === effectiveSelected)?.name}</strong> — generate the container next.
            </>
          ) : (
            <>
              <i className="fa-solid fa-circle-info me-2" />
              Select a plan to continue.
            </>
          )}
        </p>
        <button
          type="button"
          className="bgrd btn px-4 py-2 phase-cta"
          disabled={!effectiveSelected}
          onClick={() => navigate('/workflows/docker')}
        >
          Proceed to Docker Phase
          <i className="fa-solid fa-arrow-right ms-2" />
        </button>
      </div>
    </ContentContainer>
  );
}

function AssessTile({ data, title }) {
  if (!data) return null;
  return (
    <div className="surface assess-tile">
      <div className="d-flex align-items-center gap-3">
        <span className="assess-ico"><i className={`fa-solid ${data.icon}`} /></span>
        <div style={{ minWidth: 0 }}>
          <div className="assess-title">{title}</div>
          <div className="assess-value">{data.label}</div>
          <div className="assess-detail">{data.detail}</div>
        </div>
      </div>
    </div>
  );
}
