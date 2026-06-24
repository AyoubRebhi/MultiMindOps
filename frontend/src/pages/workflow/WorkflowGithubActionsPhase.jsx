import { useState } from 'react';
import { Link } from 'react-router-dom';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import EmptyState from '@/components/common/EmptyState';
import ErrorState from '@/components/common/ErrorState';
import Skeleton from '@/components/common/Skeleton';
import StatusBadge from '@/components/common/StatusBadge';
import { useGithubActionsPhase } from '@/hooks/useWorkflowRun';
import { useToast } from '@/hooks/useToast';
import { workflowApi } from '@/services/api/workflowApi';

/**
 * WorkflowGithubActionsPhase — the deployment-orchestration phase, backed by REAL
 * data. ONE read (GET .../github-actions) feeds the whole surface: the resolved
 * deployment context (target derived from the architecture decision, region and
 * the resource names Terraform creates), the consumed Docker + Terraform
 * artifacts, the YAML validation result, and the generated
 * `.github/workflows/deploy.yml`. Generation is triggered through the backend
 * (POST .../phases/GITHUB_ACTIONS_GENERATION); the frontend never mutates state
 * or fabricates a workflow file.
 *
 * @param {{ workflowId: string, workflow: object, onAdvance?: () => void }} props
 */
export default function WorkflowGithubActionsPhase({ workflowId, workflow, onAdvance }) {
  const projectId = workflow?.projectId;
  const toast = useToast();
  const { data, loading, error, refetch } = useGithubActionsPhase(projectId, workflowId);
  const [generating, setGenerating] = useState(false);

  async function handleGenerate() {
    if (!projectId || generating) return;
    setGenerating(true);
    try {
      await workflowApi.runGithubActionsPhase(projectId, workflowId);
      toast.success('Deployment workflow generated.');
      await refetch();
      onAdvance?.();
    } catch (e) {
      toast.error(e?.message || 'Could not generate the deployment workflow. Please try again.');
    } finally {
      setGenerating(false);
    }
  }

  /* ── Hard transport failure ──────────────────────────────────────────────── */
  if (error && !data) {
    return (
      <Shell status="failed">
        <ErrorState
          title="Couldn't load the GitHub Actions phase"
          message={error.message}
          onRetry={refetch}
        />
      </Shell>
    );
  }

  /* ── First load ──────────────────────────────────────────────────────────── */
  if (loading && !data) {
    return (
      <Shell status={workflow?.status}>
        <PhaseSkeletons />
      </Shell>
    );
  }

  /* ── Not generated yet → offer to run the phase ──────────────────────────── */
  if (!data || !data.generated) {
    return (
      <Shell status="running">
        <NotGenerated projectId={projectId} generating={generating} onGenerate={handleGenerate} />
      </Shell>
    );
  }

  const done = data.phaseStatus === 'completed';
  const pipelines = Array.isArray(data.pipelines) ? data.pipelines.filter((p) => p && p.content) : [];
  const hasPipelines = pipelines.length > 0;

  return (
    <Shell
      status={done ? 'completed' : workflow?.status}
      actions={
        <button
          type="button"
          className="boc btn px-3 py-2"
          style={{ fontSize: '.82rem' }}
          disabled={generating}
          onClick={handleGenerate}
        >
          {generating ? <span className="spinner me-2" /> : <i className="fa-solid fa-rotate-right me-2" />}
          Regenerate
        </button>
      }
    >
      <DeploymentSummary ctx={data.deploymentContext} target={data.deploymentTarget} template={data.template} />

      {hasPipelines ? (
        /* New: the bootstrap/deploy split — Infrastructure + Delivery pipelines. */
        <>
          <LifecycleLegend />
          {pipelines.map((p) => (
            <PipelineCard key={p.path || p.kind} pipeline={p} toast={toast} />
          ))}
        </>
      ) : (
        /* Fallback: a legacy single-file run still renders the old deploy view. */
        <>
          <ValidationCard validation={data.validation} enrichmentApplied={data.enrichmentApplied} />
          <WorkflowFileViewer file={data.workflowFile} toast={toast} />
        </>
      )}
    </Shell>
  );
}

/* ── Pipeline metadata (kind → identity, icon, trigger, lifecycle copy) ──────── */

const PIPELINE_META = {
  bootstrap: {
    title: 'Infrastructure Pipeline',
    file: 'bootstrap.yml',
    icon: 'fa-screwdriver-wrench',
    color: '#a78bfa',
    purpose: 'Infrastructure provisioning',
    description: 'Creates and updates infrastructure.',
    trigger: 'workflow_dispatch (manual)',
  },
  deploy: {
    title: 'Delivery Pipeline',
    file: 'deploy.yml',
    icon: 'fa-cloud-arrow-up',
    color: '#22c55e',
    purpose: 'Continuous delivery',
    description: 'Deploys application changes.',
    trigger: 'push + workflow_dispatch',
  },
};

function pipelineMeta(kind) {
  return PIPELINE_META[kind] || {
    title: 'Pipeline',
    file: 'workflow.yml',
    icon: 'fa-file-code',
    color: '#94a3b8',
    purpose: 'GitHub Actions workflow',
    description: '',
    trigger: 'workflow_dispatch',
  };
}

/* ── Lifecycle legend (explains the two stages of the DevOps lifecycle) ──────── */

function LifecycleLegend() {
  return (
    <div className="surface mt-3 d-flex align-items-center flex-wrap gap-3" style={{ fontSize: '.78rem' }}>
      <span className="d-flex align-items-center gap-2">
        <i className="fa-solid fa-screwdriver-wrench" style={{ color: PIPELINE_META.bootstrap.color }} />
        <strong>Infrastructure Pipeline</strong>
        <span className="text-muted">creates and updates infrastructure.</span>
      </span>
      <i className="fa-solid fa-arrow-right text-muted d-none d-md-inline" />
      <span className="d-flex align-items-center gap-2">
        <i className="fa-solid fa-cloud-arrow-up" style={{ color: PIPELINE_META.deploy.color }} />
        <strong>Delivery Pipeline</strong>
        <span className="text-muted">deploys application changes.</span>
      </span>
    </div>
  );
}

/* ── One pipeline card: identity + meta + validation + YAML viewer ───────────── */

function PipelineCard({ pipeline, toast }) {
  const meta = pipelineMeta(pipeline.kind);
  const title = pipeline.name || meta.title;
  const filename = (pipeline.path || '').split('/').pop() || meta.file;
  const v = pipeline.validation || { status: 'not_run', errors: [], warnings: [] };

  async function copy() {
    try {
      await navigator.clipboard.writeText(pipeline.content || '');
      toast.success(`${filename} copied to clipboard.`);
    } catch {
      toast.error('Could not copy to clipboard.');
    }
  }

  return (
    <div
      className="surface mt-3"
      style={{ borderLeft: `3px solid ${meta.color}` }}
    >
      {/* Header: icon + identity + copy */}
      <div className="d-flex align-items-start justify-content-between flex-wrap gap-2">
        <div className="d-flex align-items-center gap-2">
          <i className={`fa-solid ${meta.icon}`} style={{ color: meta.color, fontSize: '1.05rem' }} />
          <div>
            <div className="d-flex align-items-center gap-2">
              <strong style={{ fontSize: '.95rem' }}>{title}</strong>
              <code style={{ fontSize: '.74rem' }}>{filename}</code>
              {pipeline.version != null && (
                <span className="text-muted" style={{ fontSize: '.72rem' }}>v{pipeline.version}</span>
              )}
            </div>
            <div className="text-muted" style={{ fontSize: '.78rem' }}>{meta.description}</div>
          </div>
        </div>
        <button type="button" className="boc btn px-3 py-1" style={{ fontSize: '.78rem' }} onClick={copy}>
          <i className="fa-regular fa-copy me-2" />Copy
        </button>
      </div>

      {/* Meta strip: purpose · trigger · template · validation */}
      <div className="d-flex flex-wrap gap-2 mt-3">
        <MetaChip icon="fa-bullseye" label="Purpose" value={meta.purpose} />
        <MetaChip icon="fa-bolt" label="Trigger" value={meta.trigger} mono />
        {pipeline.template && <MetaChip icon="fa-layer-group" label="Template" value={pipeline.template} mono />}
        <PipelineValidationChip validation={v} />
        {pipeline.enrichmentApplied && (
          <span className="badge bg-info text-dark align-self-center" style={{ fontSize: '.7rem' }}>
            <i className="fa-solid fa-wand-magic-sparkles me-1" />LLM enriched
          </span>
        )}
      </div>

      {/* Validation messages (if any) */}
      {v.errors.length > 0 && (
        <ul className="mt-2 mb-0" style={{ fontSize: '.76rem', color: '#ef4444' }}>
          {v.errors.map((e, i) => <li key={i}>{e}</li>)}
        </ul>
      )}
      {v.warnings.length > 0 && (
        <ul className="mt-2 mb-0" style={{ fontSize: '.76rem', color: '#eab308' }}>
          {v.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}

      {/* YAML viewer */}
      <pre
        className="mb-0 mt-3"
        style={{
          maxHeight: 420,
          overflow: 'auto',
          background: 'rgba(0,0,0,.35)',
          borderRadius: 8,
          padding: '12px 14px',
          fontSize: '.76rem',
          lineHeight: 1.5,
        }}
      >
        <code>{pipeline.content}</code>
      </pre>
      <p className="text-muted mt-2 mb-0" style={{ fontSize: '.74rem' }}>
        Commit this file to <code>{pipeline.path || `.github/workflows/${filename}`}</code>.
      </p>
    </div>
  );
}

function MetaChip({ icon, label, value, mono }) {
  return (
    <div className="surface" style={{ padding: '6px 10px' }}>
      <div className="text-muted d-flex align-items-center gap-1" style={{ fontSize: '.66rem' }}>
        <i className={`fa-solid ${icon}`} />{label}
      </div>
      <div style={{ fontSize: '.8rem', fontFamily: mono ? 'monospace' : undefined }}>{value}</div>
    </div>
  );
}

function PipelineValidationChip({ validation }) {
  const status = validation.status || 'not_run';
  const map = {
    passed: { icon: 'fa-circle-check', color: '#22c55e', text: 'Validation passed' },
    warnings: { icon: 'fa-triangle-exclamation', color: '#eab308', text: 'Validation warnings' },
    failed: { icon: 'fa-circle-xmark', color: '#ef4444', text: 'Validation failed' },
    not_run: { icon: 'fa-circle-minus', color: '#94a3b8', text: 'Not validated' },
  };
  const m = map[status] || map.not_run;
  return (
    <div className="surface d-flex align-items-center gap-2" style={{ padding: '6px 10px' }}>
      <i className={`fa-solid ${m.icon}`} style={{ color: m.color }} />
      <span style={{ fontSize: '.8rem' }}>{m.text}</span>
    </div>
  );
}

/* ── Layout shell: timeline + phase header + content ───────────────────────── */

function Shell({ status, actions, children }) {
  const state = status === 'completed' ? 'completed' : status === 'failed' ? 'failed' : 'running';
  return (
    <>
      <WorkflowTimeline
        current="cicd"
        navigable={false}
        statuses={{
          analysis: 'completed',
          planning: 'completed',
          docker: 'completed',
          terraform: 'completed',
          'terraform-validate': 'completed',
          'terraform-plan': 'completed',
          cicd: state,
        }}
      />
      <WorkflowPhaseHeader
        icon="fa-github"
        brand
        eyebrow="Phase 7 · Deployment Orchestration"
        title="GitHub Actions Generation"
        subtitle="Generate the GitHub Actions pipelines that represent the full DevOps lifecycle — an Infrastructure pipeline (bootstrap.yml) that provisions and updates your Terraform infrastructure, and a Delivery pipeline (deploy.yml) that ships application changes. Targets are derived from your architecture decision."
        status={status}
        actions={actions}
      />
      {children}
    </>
  );
}

/* ── Deployment context summary ────────────────────────────────────────────── */

const TARGET_LABEL = {
  ecs: 'Amazon ECS',
  eks: 'Amazon EKS',
  lambda: 'AWS Lambda',
  ec2: 'Amazon EC2',
};

function DeploymentSummary({ ctx, target, template }) {
  const rows = [
    ['AWS region', ctx.awsRegion],
    ['ECR repository', ctx.repositoryName],
    target === 'eks' || target === 'ecs' ? ['Cluster', ctx.clusterName] : null,
    target === 'ecs' ? ['Service', ctx.serviceName] : null,
    target === 'lambda' ? ['Function', ctx.functionName] : null,
    ['Terraform directory', ctx.terraformDirectory],
    ['Container port', ctx.containerPort != null ? String(ctx.containerPort) : null],
  ].filter(Boolean);

  return (
    <div className="surface mt-3">
      <div className="d-flex align-items-center justify-content-between flex-wrap gap-2">
        <div className="d-flex align-items-center gap-2">
          <i className="fa-solid fa-rocket" style={{ opacity: 0.7 }} />
          <strong style={{ fontSize: '.92rem' }}>Deployment target</strong>
          <span className="badge bg-secondary" style={{ fontSize: '.72rem' }}>
            {TARGET_LABEL[target] || target || 'unknown'}
          </span>
        </div>
        {template && (
          <span className="text-muted" style={{ fontSize: '.74rem' }}>
            template: {template}
          </span>
        )}
      </div>

      <div className="row g-2 mt-2">
        {rows.map(([label, value]) => (
          <div className="col-6 col-lg-4" key={label}>
            <div className="surface h-100">
              <div className="text-muted" style={{ fontSize: '.7rem' }}>{label}</div>
              <div style={{ fontSize: '.82rem', wordBreak: 'break-all' }}>{value || '—'}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3" style={{ fontSize: '.78rem' }}>
        <div className="text-muted mb-1">Consumes validated artifacts</div>
        <div className="d-flex flex-wrap gap-2">
          {ctx.dockerArtifacts.map((a) => (
            <span key={`d-${a}`} className="badge bg-dark" style={{ fontSize: '.7rem' }}>
              <i className="fa-brands fa-docker me-1" />{a}
            </span>
          ))}
          {ctx.terraformArtifacts.map((a) => (
            <span key={`t-${a}`} className="badge bg-dark" style={{ fontSize: '.7rem' }}>
              <i className="fa-solid fa-cubes me-1" />{a}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Validation card ───────────────────────────────────────────────────────── */

function ValidationCard({ validation, enrichmentApplied }) {
  const ok = validation.status === 'passed';
  const warn = validation.status === 'warnings';
  return (
    <div className="surface mt-3">
      <div className="d-flex align-items-center gap-2">
        <i
          className={`fa-solid ${ok ? 'fa-circle-check' : warn ? 'fa-triangle-exclamation' : 'fa-circle-xmark'}`}
          style={{ color: ok ? '#22c55e' : warn ? '#eab308' : '#ef4444' }}
        />
        <strong style={{ fontSize: '.9rem' }}>YAML validation</strong>
        <StatusBadge status={ok ? 'completed' : warn ? 'running' : 'failed'} />
        {enrichmentApplied && (
          <span className="badge bg-info text-dark" style={{ fontSize: '.7rem' }}>
            <i className="fa-solid fa-wand-magic-sparkles me-1" />LLM enriched
          </span>
        )}
      </div>
      {validation.errors.length > 0 && (
        <ul className="mt-2 mb-0" style={{ fontSize: '.78rem', color: '#ef4444' }}>
          {validation.errors.map((e, i) => <li key={i}>{e}</li>)}
        </ul>
      )}
      {validation.warnings.length > 0 && (
        <ul className="mt-2 mb-0" style={{ fontSize: '.78rem', color: '#eab308' }}>
          {validation.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}
    </div>
  );
}

/* ── Generated workflow file viewer ────────────────────────────────────────── */

function WorkflowFileViewer({ file, toast }) {
  if (!file) return null;
  async function copy() {
    try {
      await navigator.clipboard.writeText(file.content);
      toast.success('Workflow copied to clipboard.');
    } catch {
      toast.error('Could not copy to clipboard.');
    }
  }
  return (
    <div className="surface mt-3">
      <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-2">
        <div className="d-flex align-items-center gap-2">
          <i className="fa-regular fa-file-code" style={{ opacity: 0.7 }} />
          <code style={{ fontSize: '.8rem' }}>{file.path}</code>
          {file.version != null && (
            <span className="text-muted" style={{ fontSize: '.72rem' }}>v{file.version}</span>
          )}
        </div>
        <button type="button" className="boc btn px-3 py-1" style={{ fontSize: '.78rem' }} onClick={copy}>
          <i className="fa-regular fa-copy me-2" />Copy
        </button>
      </div>
      <pre
        className="mb-0"
        style={{
          maxHeight: 460,
          overflow: 'auto',
          background: 'rgba(0,0,0,.35)',
          borderRadius: 8,
          padding: '12px 14px',
          fontSize: '.76rem',
          lineHeight: 1.5,
        }}
      >
        <code>{file.content}</code>
      </pre>
      <p className="text-muted mt-2 mb-0" style={{ fontSize: '.74rem' }}>
        Commit this file to <code>.github/workflows/deploy.yml</code> and add the
        <code> AWS_ACCESS_KEY_ID</code> / <code>AWS_SECRET_ACCESS_KEY</code> repository
        secrets to enable the deployment.
      </p>
    </div>
  );
}

/* ── States ────────────────────────────────────────────────────────────────── */

function NotGenerated({ projectId, generating, onGenerate }) {
  return (
    <EmptyState
      icon="fa-github"
      title="No deployment pipelines generated yet"
      message="Docker and Terraform are ready — generate the GitHub Actions pipelines that ship them: an Infrastructure pipeline (bootstrap.yml) that provisions your Terraform infrastructure, and a Delivery pipeline (deploy.yml) for continuous delivery. The deployment target (ECS / EKS / Lambda / EC2) is derived from your selected architecture; each pipeline is rendered from a vetted template and validated before it's saved."
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
              <><i className="fa-brands fa-github me-2" />Generate deployment pipelines</>
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

function PhaseSkeletons() {
  return (
    <div className="mt-2">
      <div className="surface mt-2">
        <Skeleton width="30%" height={14} />
        <div className="row g-2 mt-2">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div className="col-6 col-lg-4" key={i}>
              <div className="surface">
                <Skeleton width="50%" height={10} />
                <Skeleton width="80%" height={16} className="mt-2" />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="surface mt-3">
        <Skeleton width="100%" height={12} />
        <Skeleton width="92%" height={12} className="mt-2" />
        <Skeleton width="86%" height={12} className="mt-2" />
        <Skeleton width="94%" height={12} className="mt-2" />
      </div>
    </div>
  );
}
