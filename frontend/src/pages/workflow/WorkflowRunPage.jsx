import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import Breadcrumbs from '@/components/layout/Breadcrumbs';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import ErrorState from '@/components/common/ErrorState';
import EmptyState from '@/components/common/EmptyState';
import WorkflowPhaseNav from '@/components/workflow/WorkflowPhaseNav';
import { useWorkflowRun, useWorkflowPhases } from '@/hooks/useWorkflowRun';
import {
  resolveWorkflowView,
  IMPLEMENTED_WORKFLOW_VIEWS,
  getWorkflowPhaseMeta,
} from '@/utils/constants';
import WorkflowAnalysisPhase from './WorkflowAnalysisPhase';
import ArchitecturePlanningPhase from './ArchitecturePlanningPhase';
import WorkflowDockerPhase from './WorkflowDockerPhase';
import WorkflowTerraformPhase from './WorkflowTerraformPhase';
import WorkflowGithubActionsPhase from './WorkflowGithubActionsPhase';
import WorkflowRepositoryInstallationPhase from './WorkflowRepositoryInstallationPhase';
import WorkflowMonitoringPhase from './WorkflowMonitoringPhase';
import WorkflowInfrastructureDestroyPhase from './WorkflowInfrastructureDestroyPhase';

/**
 * WorkflowRunPage — opens a workflow and RESUMES it from its last saved phase.
 *
 * Flow (Phase 1): GET /workflows/:id → read status + current_phase →
 * resolve the phase VIEW (resolveWorkflowView) → render that phase's surface.
 * It never restarts the workflow or re-runs a phase. The phase→view mapping is
 * data-driven (utils/constants), so when a future phase becomes a real surface
 * only that map + the switch below change.
 *
 * Today Analysis, Architecture Planning, Docker Generation and Terraform
 * Generation are integrated surfaces; any other saved phase opens to an honest
 * "not available yet" panel that still reports the real current phase.
 */
export default function WorkflowRunPage() {
  const { workflowId, view: viewParam } = useParams();
  const { data: workflow, loading, error, refetch } = useWorkflowRun(workflowId);
  // Authoritative phases_state + revision history (project-scoped row). Drives
  // the revision-aware phase navigator. Loads once the summary yields projectId.
  const projectId = workflow?.projectId;
  const phasesQuery = useWorkflowPhases(projectId, workflowId);
  // Bumped after a regeneration so the active phase surface remounts + refetches
  // (its own projection changed even when the route/view did not).
  const [refreshNonce, setRefreshNonce] = useState(0);

  function handleRegenerated() {
    refetch();
    phasesQuery.refetch();
    setRefreshNonce((n) => n + 1);
  }

  if (loading && !workflow) {
    return (
      <ContentContainer>
        <Crumbs />
        <LoadingSpinner center label="Opening workflow…" />
      </ContentContainer>
    );
  }

  if (error && !workflow) {
    // 404 (not found OR not visible to this engineer) and transport errors both land here.
    const notFound = error?.status === 404 || /not found/i.test(error?.message || '');
    return (
      <ContentContainer>
        <Crumbs />
        {notFound ? (
          <EmptyState
            icon="fa-circle-question"
            title="Workflow not available"
            message="This workflow doesn't exist or you don't have access to it."
            action={
              <Link to="/workflows" className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }}>
                <i className="fa-solid fa-arrow-left me-2" />
                Back to Workflows
              </Link>
            }
          />
        ) : (
          <ErrorState
            title="Couldn't open the workflow"
            message={error.message}
            onRetry={refetch}
          />
        )}
      </ContentContainer>
    );
  }

  if (!workflow) return null;

  // An explicit, valid :view segment (from a "Proceed to …" button) wins so a
  // phase can be opened directly; otherwise resume from the saved current_phase.
  const view =
    viewParam && IMPLEMENTED_WORKFLOW_VIEWS.has(viewParam)
      ? viewParam
      : resolveWorkflowView(workflow.currentPhase);
  const projectName = workflow.projectName || 'Project';
  // Force the active phase surface to refetch its projection after a revision.
  const phaseKey = `${view}:${refreshNonce}`;
  const phasesData = phasesQuery.data;

  return (
    <ContentContainer>
      <Crumbs projectName={projectName} />

      {phasesData && (
        <WorkflowPhaseNav
          projectId={projectId}
          workflowId={workflowId}
          phasesState={phasesData.phasesState}
          currentPhase={phasesData.currentPhase || workflow.currentPhase}
          activeView={view}
          status={phasesData.status || workflow.status}
          revisions={phasesData.revisions}
          onRegenerated={handleRegenerated}
        />
      )}

      {view === 'analysis' ? (
        <WorkflowAnalysisPhase key={phaseKey} workflowId={workflowId} workflow={workflow} />
      ) : view === 'planning' ? (
        <ArchitecturePlanningPhase
          key={phaseKey}
          workflowId={workflowId}
          workflow={workflow}
          onAdvance={refetch}
        />
      ) : view === 'docker' ? (
        <WorkflowDockerPhase
          key={phaseKey}
          workflowId={workflowId}
          workflow={workflow}
          onAdvance={refetch}
        />
      ) : view === 'terraform' ? (
        <WorkflowTerraformPhase
          key={phaseKey}
          workflowId={workflowId}
          workflow={workflow}
          onAdvance={refetch}
        />
      ) : view === 'github_actions' ? (
        <WorkflowGithubActionsPhase
          key={phaseKey}
          workflowId={workflowId}
          workflow={workflow}
          onAdvance={refetch}
        />
      ) : view === 'repository_installation' ? (
        <WorkflowRepositoryInstallationPhase
          key={phaseKey}
          workflowId={workflowId}
          workflow={workflow}
          onAdvance={refetch}
        />
      ) : view === 'monitoring' ? (
        <WorkflowMonitoringPhase key={phaseKey} workflowId={workflowId} workflow={workflow} />
      ) : view === 'destroy' ? (
        <WorkflowInfrastructureDestroyPhase
          key={phaseKey}
          workflowId={workflowId}
          workflow={workflow}
          onAdvance={handleRegenerated}
        />
      ) : IMPLEMENTED_WORKFLOW_VIEWS.has(view) ? (
        // Reserved: future integrated phase surfaces render here.
        <WorkflowAnalysisPhase key={phaseKey} workflowId={workflowId} workflow={workflow} />
      ) : (
        <PhaseNotAvailable phase={workflow.currentPhase} projectId={workflow.projectId} />
      )}
    </ContentContainer>
  );
}

/** Honest placeholder for a phase that exists in the run but isn't yet a real surface. */
function PhaseNotAvailable({ phase, projectId }) {
  const meta = getWorkflowPhaseMeta(phase);
  return (
    <EmptyState
      icon={meta.icon || 'fa-diagram-project'}
      title={`${meta.label} — phase in progress`}
      message={
        `This workflow is currently at the “${meta.label}” phase. That surface ` +
        `isn't available in this build yet — the Analysis phase is the integrated one. ` +
        `You can still review the project's analysis from its detail page.`
      }
      action={
        projectId ? (
          <Link to={`/projects/${projectId}`} className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }}>
            <i className="fa-solid fa-folder-open me-2" />
            Open project
          </Link>
        ) : null
      }
    />
  );
}

function Crumbs({ projectName }) {
  return (
    <Breadcrumbs
      items={[
        { label: 'Workflows', to: '/workflows' },
        { label: projectName || 'Workflow' },
      ]}
    />
  );
}
