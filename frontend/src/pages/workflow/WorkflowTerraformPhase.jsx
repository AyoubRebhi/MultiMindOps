import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import TerraformFileViewer from '@/components/workflow/TerraformFileViewer';
import TerraformValidationConsole from '@/components/workflow/terraform/TerraformValidationConsole';
import TerraformValidationReport from '@/components/workflow/terraform/TerraformValidationReport';
import TerraformInfrastructureSummary from '@/components/workflow/terraform/TerraformInfrastructureSummary';
import EmptyState from '@/components/common/EmptyState';
import ErrorState from '@/components/common/ErrorState';
import Skeleton from '@/components/common/Skeleton';
import { useTerraformPhase } from '@/hooks/useWorkflowRun';
import { useTerraformValidation } from '@/hooks/useTerraformValidation';
import { useToast } from '@/hooks/useToast';
import { workflowApi, normalizeInfrastructureSummary } from '@/services/api/workflowApi';
import { getStatusMeta } from '@/utils/constants';

/** Map a phases_state phase status to a timeline node state. */
function phaseTimelineState(status) {
  if (status === 'completed') return 'completed';
  if (status === 'failed') return 'failed';
  if (status === 'running') return 'running';
  return 'not_started';
}

/** Recover the backing task_id from a running phase's stream_key ("id::phase"). */
function taskIdFromStreamKey(streamKey) {
  const key = String(streamKey || '');
  return key.includes('::') ? key.split('::')[0] : null;
}

/**
 * WorkflowTerraformPhase — the Infrastructure-as-Code phase (Phase 2A Generation
 * + Phase 2B Validation), backed by REAL data. Phase status is read EXCLUSIVELY
 * from the workflow's `phases_state` (TERRAFORM_GENERATION / TERRAFORM_VALIDATION);
 * the generated `.tf` files and the `validation_report` come from the persisted
 * project artifacts. Generation runs inline
 * (POST .../phases/TERRAFORM_GENERATION → TerraformAgent, LLM → DB → rehydrate).
 * Validation is a durable, STREAMED job
 * (POST .../phases/TERRAFORM_VALIDATION → terraform init + validate) whose live
 * logs flow over WS /ws/terraform/:taskId/terraform_validate via
 * useTerraformValidation; on completion the surface refetches phases_state + the
 * report. The frontend never mutates workflow state or fabricates HCL.
 *
 * Phase 2C (Plan) is wired the SAME way as Validation: once
 * TERRAFORM_VALIDATION is completed the surface offers "Run Terraform Plan"
 * (POST .../phases/TERRAFORM_PLAN → durable streamed job), live logs flow over
 * the SAME socket namespaced as `terraform_plan`, status is read from
 * phases_state.TERRAFORM_PLAN, and on completion the persisted Infrastructure
 * Summary + raw plan.json are shown.
 *
 * Out of scope (later phases): Terraform Apply, Cost.
 *
 * @param {{ workflowId: string, workflow: object, onAdvance?: () => void }} props
 */
export default function WorkflowTerraformPhase({ workflowId, workflow, onAdvance }) {
  const projectId = workflow?.projectId;
  const toast = useToast();
  const { data, loading, error, refetch } = useTerraformPhase(projectId, workflowId);
  const [generating, setGenerating] = useState(false);

  // Authoritative phase status comes ONLY from phases_state (never inferred from
  // the presence of artifacts).
  const gen = data?.phasesState?.TERRAFORM_GENERATION || null;
  const genStatus = gen?.status || null; // completed | completed_no_files | failed | running | null
  const generated = genStatus === 'completed' || genStatus === 'completed_no_files';
  const failed = genStatus === 'failed';
  // Generation can complete with HCL while the inline validation reported issues.
  // That is NOT a generation failure — surface it as a non-blocking warning and
  // steer the user to the dedicated Terraform Validation phase.
  const genValidationFailed = gen?.validation_status === 'failed';
  const artifacts = data?.artifacts || [];

  // ── Validation phase state — read EXCLUSIVELY from phases_state ────────────
  const tfv = data?.phasesState?.TERRAFORM_VALIDATION || null;
  const tfvStatus = tfv?.status || null; // running | completed | failed | null
  const validationReport = data?.validationReport || null;
  const resumedTaskId = taskIdFromStreamKey(tfv?.stream_key);

  const [validating, setValidating] = useState(false);
  const [, setTaskId] = useState(null);
  const autoConnectedRef = useRef(null);

  // ── Plan phase state — read EXCLUSIVELY from phases_state ──────────────────
  const tfp = data?.phasesState?.TERRAFORM_PLAN || null;
  const tfpStatus = tfp?.status || null; // running | completed | failed | null
  const resumedPlanTaskId = taskIdFromStreamKey(tfp?.stream_key);
  // Infrastructure Summary: prefer the copy embedded in the phase entry (no
  // second parse), fall back to the standalone artifact (useTerraformPhase).
  const infrastructureSummary =
    normalizeInfrastructureSummary(tfp?.infrastructure_summary) ||
    data?.infrastructureSummary ||
    null;
  const planArtifact = data?.planArtifact || null;

  const [planning, setPlanning] = useState(false);
  const [, setPlanTaskId] = useState(null);
  const autoConnectedPlanRef = useRef(null);

  async function handleGenerate() {
    if (!projectId || generating) return;
    setGenerating(true);
    try {
      await workflowApi.runTerraformPhase(projectId, workflowId, 'TERRAFORM_GENERATION');
      toast.success('Terraform configuration generated by the Terraform agent.');
      await refetch();
      onAdvance?.();
    } catch (e) {
      toast.error(e?.message || 'Could not generate Terraform. Please try again.');
    } finally {
      setGenerating(false);
    }
  }

  // When a validation stream ends, re-read phases_state + the validation report.
  const handleValidationComplete = useCallback(async () => {
    await refetch();
  }, [refetch]);

  // Pass the AUTHORITATIVE phase status so the hook gates reconnects on
  // phases_state (not the ephemeral WS status).
  const validation = useTerraformValidation({
    onComplete: handleValidationComplete,
    phaseStatus: tfvStatus,
  });
  const { connect: connectValidation } = validation;

  // Run (or re-run) validation: enqueue the durable job, capture its task_id,
  // then attach the live socket. The backend owns the transition; we refetch so
  // phases_state shows TERRAFORM_VALIDATION = running immediately.
  async function handleRunValidation() {
    if (!projectId || validating) return;
    setValidating(true);
    try {
      const res = await workflowApi.runTerraformValidation(projectId, workflowId);
      if (res?.taskId) {
        setTaskId(res.taskId);
        autoConnectedRef.current = res.taskId;
        connectValidation(res.taskId);
      }
      toast.success('Terraform validation started.');
      await refetch();
    } catch (e) {
      toast.error(e?.message || 'Could not start Terraform validation. Please try again.');
    } finally {
      setValidating(false);
    }
  }

  // Resume: if validation is already running for this workflow (e.g. after a page
  // reload), attach the live socket once using the task_id recovered from the
  // phase's stream_key.
  useEffect(() => {
    if (
      tfvStatus === 'running' &&
      resumedTaskId &&
      autoConnectedRef.current !== resumedTaskId
    ) {
      autoConnectedRef.current = resumedTaskId;
      connectValidation(resumedTaskId);
    }
  }, [tfvStatus, resumedTaskId, connectValidation]);

  // ── Plan: same streamed-job pattern as Validation, namespaced terraform_plan ─
  const handlePlanComplete = useCallback(async () => {
    await refetch();
  }, [refetch]);

  const plan = useTerraformValidation({
    onComplete: handlePlanComplete,
    phaseStatus: tfpStatus,
    jobPhase: 'terraform_plan',
  });
  const { connect: connectPlan } = plan;

  // Run (or re-run) plan: enqueue the durable job, capture its task_id, then
  // attach the live socket. The backend owns the transition; we refetch so
  // phases_state shows TERRAFORM_PLAN = running immediately.
  async function handleRunPlan() {
    if (!projectId || planning) return;
    setPlanning(true);
    try {
      const res = await workflowApi.runTerraformPlan(projectId, workflowId);
      if (res?.taskId) {
        setPlanTaskId(res.taskId);
        autoConnectedPlanRef.current = res.taskId;
        connectPlan(res.taskId);
      }
      toast.success('Terraform plan started.');
      await refetch();
    } catch (e) {
      toast.error(e?.message || 'Could not start Terraform plan. Please try again.');
    } finally {
      setPlanning(false);
    }
  }

  // Resume: if plan is already running (after a reload), attach the live socket
  // once using the task_id recovered from the phase's stream_key.
  useEffect(() => {
    if (
      tfpStatus === 'running' &&
      resumedPlanTaskId &&
      autoConnectedPlanRef.current !== resumedPlanTaskId
    ) {
      autoConnectedPlanRef.current = resumedPlanTaskId;
      connectPlan(resumedPlanTaskId);
    }
  }, [tfpStatus, resumedPlanTaskId, connectPlan]);

  /* ── Hard transport failure ──────────────────────────────────────────────── */
  if (error && !data) {
    return (
      <TerraformShell status="failed">
        <ErrorState
          title="Couldn't load the Terraform phase"
          message={error.message}
          onRetry={refetch}
        />
      </TerraformShell>
    );
  }

  /* ── First load ──────────────────────────────────────────────────────────── */
  if (loading && !data) {
    return (
      <TerraformShell status={workflow?.status}>
        <TerraformSkeletons />
      </TerraformShell>
    );
  }

  /* ── Not generated yet (or generation failed) → offer to run the phase ─────── */
  if (!generated) {
    return (
      <TerraformShell status={failed ? 'failed' : 'running'}>
        <NotGenerated
          projectId={projectId}
          generating={generating}
          failed={failed}
          onGenerate={handleGenerate}
        />
      </TerraformShell>
    );
  }

  /* ── Generated, but the plan produced no .tf files ────────────────────────── */
  if (!artifacts.length) {
    return (
      <TerraformShell
        status="completed"
        actions={<RegenerateButton generating={generating} onClick={handleGenerate} />}
      >
        <EmptyState
          icon="fa-cubes"
          title="Terraform generation completed — no files"
          message="The generation phase completed but produced no Terraform files for this plan. Try regenerating, or review the selected architecture plan."
        />
      </TerraformShell>
    );
  }

  /* ── Generated → metadata + .tf files + Validation + Plan ──────────────────── */
  const validateState = phaseTimelineState(tfvStatus);
  const planState = phaseTimelineState(tfpStatus);
  // Plan becomes available once validation has completed; it also stays visible
  // once it has any state of its own (so a reload mid/after-plan still shows it).
  const showPlan = tfvStatus === 'completed' || !!tfpStatus;
  return (
    <TerraformShell
      status="completed"
      validateState={validateState}
      planState={planState}
      actions={<RegenerateButton generating={generating} onClick={handleGenerate} />}
    >
      {genValidationFailed && (
        <GenerationValidationWarning classification={gen?.failure_classification} />
      )}
      <GenerationSummary gen={gen} fileCount={artifacts.length} />
      <div className="mt-3">
        <TerraformFileViewer files={artifacts} />
      </div>

      <ValidationSection
        tfvStatus={tfvStatus}
        validation={validation}
        report={validationReport}
        running={validating || tfvStatus === 'running' || validation.running}
        onRun={handleRunValidation}
      />

      {showPlan && (
        <PlanSection
          tfpStatus={tfpStatus}
          plan={plan}
          summary={infrastructureSummary}
          planArtifact={planArtifact}
          running={planning || tfpStatus === 'running' || plan.running}
          onRun={handleRunPlan}
        />
      )}
    </TerraformShell>
  );
}

/* ── Validation: run button + live logs + persisted report ──────────────────── */

function ValidationSection({ tfvStatus, validation, report, running, onRun }) {
  const meta = getStatusMeta(tfvStatus || 'not_started');
  const runLabel =
    tfvStatus === 'failed' ? 'Re-run validation'
      : tfvStatus === 'completed' ? 'Re-run validation'
        : 'Run Terraform Validation';

  // Console source: live WS logs while a run is active; otherwise rehydrate from
  // the persisted validation_report so output survives reconnects AND page
  // reloads (the WS no longer streams once the phase is terminal).
  const liveLogs = validation.logs;
  const consoleLogs = liveLogs.length ? liveLogs : reportToConsoleLines(report);
  const consoleStatus = liveLogs.length
    ? validation.status
    : tfvStatus === 'completed'
      ? 'success'
      : tfvStatus === 'failed'
        ? 'failed'
        : validation.status;
  const hasConsole = consoleLogs.length > 0 || running;

  return (
    <>
      <div className="section-label mt-4">
        <span className="section-label-chip">
          <i className="fa-solid fa-clipboard-check" />
        </span>
        Terraform Validation
        <span className="section-label-by">terraform init + validate · live logs</span>
      </div>

      <div className="surface d-flex align-items-center gap-3 flex-wrap mb-2">
        <button
          type="button"
          className="bgrd btn px-4 py-2"
          style={{ fontSize: '.85rem' }}
          disabled={running}
          onClick={onRun}
        >
          {running ? (
            <><span className="spinner me-2" />Validating…</>
          ) : (
            <><i className="fa-solid fa-clipboard-check me-2" />{runLabel}</>
          )}
        </button>
        <span style={{ fontSize: '.8rem', color: 'var(--tx2)' }}>
          {tfvStatus ? (
            <>
              <i className={`fa-solid ${meta.icon} me-2`} style={{ color: 'var(--tx3)' }} />
              Validation status: <strong>{meta.label}</strong>
            </>
          ) : (
            <>
              <i className="fa-solid fa-circle-info me-2" style={{ color: 'var(--tx3)' }} />
              Runs <span className="mono">terraform init</span> + <span className="mono">validate</span> against the generated configuration.
            </>
          )}
        </span>
      </div>

      {/* Live logs while running; after a reconnect/reload the persisted
          validation_report rehydrates the console so output is never lost. */}
      {hasConsole && (
        <TerraformValidationConsole
          logs={consoleLogs}
          status={consoleStatus}
          connectionState={liveLogs.length ? validation.connectionState : 'idle'}
          exitCode={validation.exitCode}
          onReconnect={validation.reconnect}
        />
      )}

      {/* Persisted report (validation_report artifact) — present after a run settles. */}
      {report && (
        <div className="mt-2">
          <TerraformValidationReport report={report} />
        </div>
      )}
    </>
  );
}

/* ── Plan: run button (gated on validation completed) + live logs + summary ──── */

function PlanSection({ tfpStatus, plan, summary, planArtifact, running, onRun }) {
  const meta = getStatusMeta(tfpStatus || 'not_started');
  const runLabel =
    tfpStatus === 'failed' ? 'Re-run plan'
      : tfpStatus === 'completed' ? 'Re-run plan'
        : 'Run Terraform Plan';

  const liveLogs = plan.logs;
  const consoleStatus = liveLogs.length
    ? plan.status
    : tfpStatus === 'completed'
      ? 'success'
      : tfpStatus === 'failed'
        ? 'failed'
        : plan.status;
  const hasConsole = liveLogs.length > 0 || running;

  return (
    <>
      <div className="section-label mt-4">
        <span className="section-label-chip">
          <i className="fa-solid fa-diagram-project" />
        </span>
        Terraform Plan
        <span className="section-label-by">terraform init + plan · live logs</span>
      </div>

      <div className="surface d-flex align-items-center gap-3 flex-wrap mb-2">
        <button
          type="button"
          className="bgrd btn px-4 py-2"
          style={{ fontSize: '.85rem' }}
          disabled={running}
          onClick={onRun}
        >
          {running ? (
            <><span className="spinner me-2" />Planning…</>
          ) : (
            <><i className="fa-solid fa-diagram-project me-2" />{runLabel}</>
          )}
        </button>
        <span style={{ fontSize: '.8rem', color: 'var(--tx2)' }}>
          {tfpStatus ? (
            <>
              <i className={`fa-solid ${meta.icon} me-2`} style={{ color: 'var(--tx3)' }} />
              Plan status: <strong>{meta.label}</strong>
            </>
          ) : (
            <>
              <i className="fa-solid fa-circle-info me-2" style={{ color: 'var(--tx3)' }} />
              Runs <span className="mono">terraform init</span> + <span className="mono">plan</span> and summarizes the infrastructure it would create.
            </>
          )}
        </span>
      </div>

      {/* Live logs while a plan run is active (reuses the validation console). */}
      {hasConsole && (
        <TerraformValidationConsole
          logs={liveLogs}
          status={consoleStatus}
          connectionState={liveLogs.length ? plan.connectionState : 'idle'}
          exitCode={plan.exitCode}
          onReconnect={plan.reconnect}
          title="terraform plan"
        />
      )}

      {/* Persisted Infrastructure Summary — present after a successful plan. */}
      {summary && (
        <div className="mt-2">
          <TerraformInfrastructureSummary summary={summary} />
        </div>
      )}

      {/* Raw machine-readable plan (terraform show -json) — collapsed by default. */}
      {planArtifact?.content && (
        <details className="surface mt-2">
          <summary
            style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10, fontSize: '.84rem' }}
          >
            <i className="fa-solid fa-file-code" style={{ color: 'var(--tx3)' }} />
            <span className="mono" style={{ fontWeight: 600 }}>plan.json</span>
            {planArtifact.lines ? (
              <span className="text-muted-3" style={{ fontSize: '.74rem' }}>
                {planArtifact.lines} line{planArtifact.lines === 1 ? '' : 's'}
              </span>
            ) : null}
          </summary>
          <pre
            className="mono mt-2"
            style={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontSize: '.74rem',
              background: 'var(--bg2, rgba(0,0,0,.18))',
              border: '1px solid var(--bd)',
              borderRadius: 6,
              padding: '10px 12px',
              maxHeight: 360,
              overflow: 'auto',
            }}
          >
            {planArtifact.content}
          </pre>
        </details>
      )}
    </>
  );
}

/* ── Layout shell: timeline + phase header + content ───────────────────────── */

function TerraformShell({
  status,
  validateState = 'not_started',
  planState = 'not_started',
  actions,
  children,
}) {
  const tfState =
    status === 'completed' ? 'completed' : status === 'failed' ? 'failed' : 'running';
  return (
    <>
      <WorkflowTimeline
        current="terraform"
        navigable={false}
        statuses={{
          analysis: 'completed',
          planning: 'completed',
          docker: 'completed',
          terraform: tfState,
          'terraform-validate': validateState,
          'terraform-plan': planState,
        }}
      />
      <WorkflowPhaseHeader
        icon="fa-cubes"
        eyebrow="Phase 4 · Infrastructure as Code"
        title="Terraform Generation"
        subtitle="Review the AI-generated Terraform configuration (main.tf, variables.tf, outputs.tf, providers.tf) for this project's selected architecture."
        status={status}
        actions={actions}
      />
      {children}
    </>
  );
}

/* ── Pieces ────────────────────────────────────────────────────────────────── */

function RegenerateButton({ generating, onClick }) {
  return (
    <button
      type="button"
      className="boc btn px-3 py-2"
      style={{ fontSize: '.82rem' }}
      disabled={generating}
      onClick={onClick}
    >
      {generating ? <span className="spinner me-2" /> : <i className="fa-solid fa-rotate-right me-2" />}
      Regenerate
    </button>
  );
}

/**
 * Non-blocking warning: generation produced HCL but the inline validation
 * reported issues. The `.tf` files are real, persisted output — generation did
 * NOT fail. We steer the user to the dedicated Terraform Validation phase (whose
 * Run button is rendered below) to see the full report and resolve the findings.
 */
function GenerationValidationWarning({ classification }) {
  return (
    <div
      className="surface d-flex align-items-start gap-3 mb-3"
      style={{ borderLeft: '3px solid #fbbf24', padding: '12px 16px' }}
    >
      <span style={{ color: '#fbbf24', fontSize: '1rem', lineHeight: 1.4 }}>
        <i className="fa-solid fa-triangle-exclamation" />
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: '.88rem', fontWeight: 600 }}>
          Terraform generated — validation found issues
        </div>
        <p className="mb-0 mt-1" style={{ fontSize: '.8rem', color: 'var(--tx2)' }}>
          The configuration was rendered and saved successfully, but the inline
          check reported{' '}
          <strong>{classification || 'validation findings'}</strong>. This does
          not block generation. Review the files below, then run{' '}
          <strong>Terraform Validation</strong> to see the full report and
          resolve the findings.
        </p>
      </div>
    </div>
  );
}

/** Read-only summary strip — every value comes from phases_state.TERRAFORM_GENERATION. */
function GenerationSummary({ gen, fileCount }) {
  const meta = getStatusMeta(gen?.status);
  const generatedAt = gen?.updated_at ? safeDate(gen.updated_at) : null;
  const cells = [
    { label: 'Status', value: meta.label, icon: meta.icon },
    { label: 'Files', value: String(gen?.file_count ?? fileCount), icon: 'fa-file-code' },
    gen?.validation_status
      ? { label: 'Validation', value: gen.validation_status, icon: 'fa-clipboard-check' }
      : null,
    generatedAt ? { label: 'Generated', value: generatedAt, icon: 'fa-clock' } : null,
  ].filter(Boolean);

  return (
    <div className="row g-2">
      {cells.map((c) => (
        <div className="col-6 col-lg-3" key={c.label}>
          <div className="surface">
            <div className="text-muted-3" style={{ fontSize: '.72rem' }}>
              <i className={`fa-solid ${c.icon} me-2`} />
              {c.label}
            </div>
            <div className="mt-1" style={{ fontSize: '.9rem', fontWeight: 600 }}>
              {c.value}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function NotGenerated({ projectId, generating, failed, onGenerate }) {
  return (
    <EmptyState
      icon="fa-cubes"
      title={failed ? 'Terraform generation failed' : 'No Terraform generated yet'}
      message={
        failed
          ? 'The last Terraform generation attempt failed. Regenerate to try again, or review the selected architecture plan.'
          : 'A plan is selected — generate the Terraform configuration for this project. The Terraform agent renders the infrastructure (main.tf, variables.tf, outputs.tf, providers.tf) for the chosen architecture.'
      }
      action={
        <div className="d-flex gap-2 justify-content-center">
          <button
            type="button"
            className="bgrd btn px-4 py-2"
            style={{ fontSize: '.85rem' }}
            disabled={generating}
            onClick={onGenerate}
          >
            {generating ? (
              <><span className="spinner me-2" />Generating…</>
            ) : (
              <><i className="fa-solid fa-cubes me-2" />{failed ? 'Regenerate Terraform' : 'Generate Terraform'}</>
            )}
          </button>
          {projectId && (
            <Link to={`/projects/${projectId}`} className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }}>
              <i className="fa-solid fa-folder-open me-2" />
              Open project
            </Link>
          )}
        </div>
      }
    />
  );
}

function TerraformSkeletons() {
  return (
    <div className="mt-2">
      <div className="row g-2">
        {[0, 1, 2, 3].map((i) => (
          <div className="col-6 col-lg-3" key={i}>
            <div className="surface">
              <Skeleton width="50%" height={10} />
              <Skeleton width="80%" height={16} className="mt-2" />
            </div>
          </div>
        ))}
      </div>
      <div className="surface mt-3">
        <Skeleton width="30%" height={14} />
        <Skeleton width="100%" height={12} className="mt-2" />
        <Skeleton width="92%" height={12} className="mt-2" />
        <Skeleton width="86%" height={12} className="mt-2" />
        <Skeleton width="94%" height={12} className="mt-2" />
        <Skeleton width="70%" height={12} className="mt-2" />
      </div>
    </div>
  );
}

function safeDate(iso) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/**
 * Rebuild console lines from the persisted validation_report so a completed
 * validation's output survives reconnects and page reloads (when no live WS is
 * streaming). Each step contributes its `$ terraform <step>` banner, its captured
 * output, and an exit-code line — all flagged isReplay for the ↺ marker.
 */
function reportToConsoleLines(report) {
  if (!report || !Array.isArray(report.steps) || report.steps.length === 0) return [];
  const lines = [];
  for (const s of report.steps) {
    lines.push({ level: 'cmd', text: `$ terraform ${s.step}`, isReplay: true });
    if (s.output) {
      for (const ln of s.output.split('\n')) {
        lines.push({ level: s.ok ? 'info' : 'error', text: ln, isReplay: true });
      }
    }
    if (s.returnCode != null) {
      lines.push({
        level: s.ok ? 'success' : 'error',
        text: `exit code ${s.returnCode}`,
        isReplay: true,
      });
    }
  }
  return lines;
}
