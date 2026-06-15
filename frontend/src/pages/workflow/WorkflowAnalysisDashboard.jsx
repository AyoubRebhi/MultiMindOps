import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import Breadcrumbs from '@/components/layout/Breadcrumbs';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import EmptyState from '@/components/common/EmptyState';
import Skeleton from '@/components/common/Skeleton';
import { useWorkflowAnalysis } from '@/hooks/useWorkflowAnalysis';
import { useToast } from '@/hooks/useToast';

import AnalysisContextHeader from '@/components/workflow/analysis/AnalysisContextHeader';
import AnalysisActionBar from '@/components/workflow/analysis/AnalysisActionBar';
import CustomerPortalPanel from '@/components/workflow/analysis/CustomerPortalPanel';
import CodeAnalysisPanel from '@/components/workflow/analysis/CodeAnalysisPanel';
import ArchitectureIntelligencePanel from '@/components/workflow/analysis/ArchitectureIntelligencePanel';
import InfrastructureRecommendationPanel from '@/components/workflow/analysis/InfrastructureRecommendationPanel';
import SecurityContainerizationPanel from '@/components/workflow/analysis/SecurityContainerizationPanel';

/**
 * WorkflowAnalysisDashboard — the Workflow Analysis stage
 * (/workflows/:projectId/analysis).
 *
 * The single source of truth for the AI's understanding of a repository: code,
 * architecture, infrastructure, security and containerization intelligence,
 * aggregated from ONE call (useWorkflowAnalysis → workflowAnalysisApi.getAnalysis)
 * and distributed to five independent panels.
 *
 * Renders three states cleanly: RUNNING (skeletons), DONE (populated panels),
 * FAILED (failure banner + retry) — without ever breaking the page layout.
 */
const SECTIONS = [
  { n: 1, label: 'Customer Portal', by: 'Business Summary' },
  { n: 2, label: 'Code Analysis', by: 'Code Analysis Agent' },
  { n: 3, label: 'Architecture Intelligence', by: 'Architecture Agent' },
  { n: 4, label: 'Infrastructure Recommendation', by: 'Infrastructure Agent' },
  { n: 5, label: 'Security & Containerization', by: 'Security Guard Agent' },
];

export default function WorkflowAnalysisDashboard() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { data, loading, error, working, refetch, start, rerun } =
    useWorkflowAnalysis(projectId);
  const [logsOpen, setLogsOpen] = useState(false);

  const handleStart = async () => {
    try {
      await start();
      toast.info('Workflow started — analysis is running.');
    } catch (err) {
      toast.error(err?.message || 'Could not start the workflow.');
    }
  };

  const handleRerun = async () => {
    try {
      await rerun();
      toast.info('Re-running analysis on the latest commit.');
    } catch (err) {
      toast.error(err?.message || 'Could not rerun the analysis.');
    }
  };

  /* ── Hard failure: the fetch itself errored and we have nothing to show ──── */
  if (error && !data) {
    return (
      <ContentContainer>
        <Crumbs projectId={projectId} />
        <EmptyState
          icon="fa-triangle-exclamation"
          title="Couldn't load the analysis"
          message={error.message || 'The workflow analysis could not be retrieved.'}
          action={
            <button className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={refetch}>
              <i className="fa-solid fa-rotate-right me-2" />
              Retry
            </button>
          }
        />
      </ContentContainer>
    );
  }

  /* ── First load: full-page skeleton ─────────────────────────────────────── */
  if (loading && !data) {
    return (
      <ContentContainer>
        <Crumbs projectId={projectId} />
        <WorkflowTimeline current="analysis" navigable={false} />
        <HeaderSkeleton />
        <Skeleton height={56} radius={14} className="mb-3" />
        <PanelSkeletons />
      </ContentContainer>
    );
  }

  const status = data?.status || 'RUNNING';
  const isRunning = status === 'RUNNING';
  const isFailed = status === 'FAILED';
  const isDone = status === 'DONE';

  return (
    <ContentContainer>
      <Crumbs projectId={projectId} name={data?.projectInfo?.name} />

      <WorkflowTimeline
        current="analysis"
        navigable={false}
        statuses={{ analysis: isDone ? 'completed' : isFailed ? 'failed' : 'running' }}
      />

      {/* Section A — context header */}
      <AnalysisContextHeader
        project={data?.projectInfo}
        status={status}
        lastUpdated={data?.lastUpdated}
      />

      {/* Section B — action bar */}
      <AnalysisActionBar
        status={status}
        busy={working}
        onStart={handleStart}
        onRerun={handleRerun}
        onViewLogs={() => setLogsOpen((v) => !v)}
        logsOpen={logsOpen}
      />

      {/* Raw logs (View Raw Logs) */}
      {logsOpen && (
        <div className="surface mb-3">
          <div className="d-flex align-items-center justify-content-between mb-2">
            <h3 className="card-title">
              <i className="fa-solid fa-terminal me-2" style={{ color: 'var(--pur)' }} />
              Raw Analysis Payload
            </h3>
            <span className="text-muted-3" style={{ fontSize: '.74rem' }}>
              GET /api/workflows/{projectId}/analysis
            </span>
          </div>
          <pre className="mono" style={rawLogStyle}>
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      )}

      {/* FAILED banner — keeps the layout intact */}
      {isFailed && (
        <div className="surface phase-card rail-failed mb-3">
          <div className="phase-card-head">
            <div className="d-flex align-items-center gap-3" style={{ minWidth: 0 }}>
              <span className="phase-step-chip" style={{ color: '#f87171' }}>
                <i className="fa-solid fa-circle-xmark" />
              </span>
              <div>
                <h3 className="card-title">Analysis failed</h3>
                <p className="phase-card-subtitle">
                  {data?.error || 'The workflow analysis did not complete.'}
                </p>
              </div>
            </div>
            <button className="bgrd btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={handleRerun} disabled={working}>
              <i className={`fa-solid ${working ? 'fa-spinner fa-spin' : 'fa-rotate-right'} me-2`} />
              Rerun Analysis
            </button>
          </div>
        </div>
      )}

      {/* RUNNING banner */}
      {isRunning && (
        <div className="surface d-flex align-items-center gap-2 mb-3" style={{ padding: '12px 16px' }}>
          <span className="spinner" />
          <span style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>
            Analysis agents are running — results will populate below as they finish.
          </span>
        </div>
      )}

      {/* Section C — analysis panels */}
      {isRunning ? (
        <PanelSkeletons />
      ) : (
        <>
          <SectionLabel {...SECTIONS[0]} />
          <CustomerPortalPanel data={data?.customerPortal} />

          <SectionLabel {...SECTIONS[1]} />
          <CodeAnalysisPanel data={data?.codeAnalysis} />

          <SectionLabel {...SECTIONS[2]} />
          <ArchitectureIntelligencePanel data={data?.architecture} />

          <SectionLabel {...SECTIONS[3]} />
          <InfrastructureRecommendationPanel data={data?.infrastructureRecommendations} />

          <SectionLabel {...SECTIONS[4]} />
          <SecurityContainerizationPanel
            security={data?.securityAnalysis}
            containerization={data?.containerization}
          />
        </>
      )}

      {/* Advance the journey once analysis is done */}
      {isDone && (
        <div className="phase-footer">
          <p className="phase-footer-note">
            <i className="fa-solid fa-circle-info me-2" />
            Analysis complete — continue to plan the cloud architecture.
          </p>
          <button
            type="button"
            className="bgrd btn px-4 py-2 phase-cta"
            onClick={() => navigate('/workflows/planning')}
          >
            Proceed to Architecture Planning
            <i className="fa-solid fa-arrow-right ms-2" />
          </button>
        </div>
      )}
    </ContentContainer>
  );
}

/* ── Local presentational helpers ─────────────────────────────────────────── */

function Crumbs({ projectId, name }) {
  return (
    <Breadcrumbs
      items={[
        { label: 'Projects', to: '/projects' },
        { label: name || 'Project', to: `/projects/${projectId}` },
        { label: 'Workflow Analysis' },
      ]}
    />
  );
}

function SectionLabel({ n, label, by }) {
  return (
    <div className="section-label mt-4">
      <span className="section-label-chip">{n}</span>
      {label}
      <span className="section-label-by">{by}</span>
    </div>
  );
}

function HeaderSkeleton() {
  return (
    <div className="surface mb-3">
      <div className="d-flex align-items-center gap-3">
        <Skeleton width="48px" height={48} radius={12} />
        <div style={{ flex: 1 }}>
          <Skeleton width="40%" height={18} />
          <Skeleton width="30%" height={12} className="mt-2" />
        </div>
        <Skeleton width="90px" height={26} radius={20} />
      </div>
    </div>
  );
}

function PanelSkeletons() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <div className="surface mb-3" key={i}>
          <Skeleton width="32%" height={16} />
          <Skeleton width="100%" height={12} className="mt-3" />
          <Skeleton width="85%" height={12} className="mt-2" />
          <Skeleton width="60%" height={12} className="mt-2" />
          <div className="d-flex gap-2 mt-3">
            <Skeleton width="80px" height={24} radius={20} />
            <Skeleton width="80px" height={24} radius={20} />
            <Skeleton width="80px" height={24} radius={20} />
          </div>
        </div>
      ))}
    </>
  );
}

const rawLogStyle = {
  margin: 0,
  maxHeight: 320,
  overflow: 'auto',
  fontSize: '.74rem',
  lineHeight: 1.55,
  color: 'var(--tx2)',
  background: 'rgba(0,0,0,.18)',
  border: '1px solid var(--bd)',
  borderRadius: 10,
  padding: 14,
};
