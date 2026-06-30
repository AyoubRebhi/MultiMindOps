import { useState } from 'react';
import { Link } from 'react-router-dom';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import StatusBadge from '@/components/common/StatusBadge';
import ErrorState from '@/components/common/ErrorState';
import Skeleton from '@/components/common/Skeleton';
import Modal from '@/components/common/Modal';
import { useDestroyPhase } from '@/hooks/useWorkflowRun';
import { useToast } from '@/hooks/useToast';
import { workflowApi } from '@/services/api/workflowApi';

/**
 * WorkflowInfrastructureDestroyPhase — tear down the provisioned AWS resources.
 *
 * The backend NEVER runs Terraform: confirming destruction generates a
 * `destroy.yml` GitHub Actions workflow, commits it (reusing the installation
 * flow) and auto-triggers it; this surface then OBSERVES the run read-only,
 * exactly like bootstrap.yml. It guards the destructive action behind an
 * explicit, acknowledged confirmation.
 *
 * @param {{ workflowId: string, workflow: object, onAdvance?: () => void }} props
 */
export default function WorkflowInfrastructureDestroyPhase({ workflowId, workflow, onAdvance }) {
  const projectId = workflow?.projectId;
  const toast = useToast();
  const { data, loading, error, refetch } = useDestroyPhase(projectId, workflowId);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [destroying, setDestroying] = useState(false);

  async function handleDestroy() {
    if (!projectId || destroying) return;
    setDestroying(true);
    try {
      await workflowApi.runDestroyPhase(projectId, workflowId);
      toast.success('Destroy requested — destroy.yml committed and triggered.');
      setConfirmOpen(false);
      setAcknowledged(false);
      await refetch();
      onAdvance?.();
    } catch (e) {
      toast.error(e?.message || 'Could not start the destroy. Please try again.');
    } finally {
      setDestroying(false);
    }
  }

  if (error && !data) {
    return (
      <Shell status="failed">
        <ErrorState title="Couldn't load the destroy phase" message={error.message} onRetry={refetch} />
      </Shell>
    );
  }
  if (loading && !data) {
    return (
      <Shell status={workflow?.status}>
        <PhaseSkeletons />
      </Shell>
    );
  }

  const phaseStatus = data?.phaseStatus || null;
  const triggered = !!phaseStatus;
  const inFlight = data?.requested || data?.running;

  return (
    <Shell status={phaseStatus || workflow?.status} phaseStatus={phaseStatus}>
      <WarningBanner />

      {!data?.prerequisitesMet && !triggered ? (
        <PrerequisitesCard data={data} projectId={projectId} />
      ) : (
        <>
          <ActionCard
            data={data}
            inFlight={inFlight}
            disabled={!data?.prerequisitesMet || inFlight || destroying}
            onOpen={() => setConfirmOpen(true)}
            onRefresh={refetch}
          />
          {triggered && <ProvenanceCard data={data} />}
          {triggered && <RunCard data={data} />}
        </>
      )}

      <Modal
        open={confirmOpen}
        onClose={() => { setConfirmOpen(false); setAcknowledged(false); }}
        title="Destroy infrastructure?"
        icon="fa-triangle-exclamation"
        footer={
          <>
            <button
              type="button"
              className="boc btn px-3 py-2"
              style={{ fontSize: '.82rem' }}
              onClick={() => { setConfirmOpen(false); setAcknowledged(false); }}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn px-3 py-2"
              style={{ fontSize: '.82rem', background: '#ef4444', color: '#fff', opacity: acknowledged && !destroying ? 1 : 0.55 }}
              disabled={!acknowledged || destroying}
              onClick={handleDestroy}
            >
              {destroying ? <span className="spinner me-2" /> : <i className="fa-solid fa-trash-can me-2" />}
              Destroy infrastructure
            </button>
          </>
        }
      >
        <div className="surface mb-3" style={{ borderLeft: '3px solid #ef4444' }}>
          <div className="d-flex align-items-center gap-2" style={{ color: '#ef4444', fontSize: '.9rem' }}>
            <i className="fa-solid fa-triangle-exclamation" />
            <strong>This operation permanently removes AWS resources.</strong>
          </div>
          <p className="text-muted mb-0 mt-2" style={{ fontSize: '.82rem' }}>
            A <code>destroy.yml</code> workflow will be committed to your repository and triggered.
            GitHub Actions will run <code>terraform destroy -auto-approve</code>, deleting every
            resource Terraform provisioned for this project. This cannot be undone.
          </p>
        </div>
        <label className="d-flex align-items-start gap-2" style={{ fontSize: '.84rem', cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(e) => setAcknowledged(e.target.checked)}
            style={{ marginTop: 3 }}
          />
          <span>I understand this permanently removes the AWS resources for this project.</span>
        </label>
      </Modal>
    </Shell>
  );
}

/* ── Layout shell ───────────────────────────────────────────────────────────── */

function Shell({ status, phaseStatus, children }) {
  return (
    <>
      <WorkflowPhaseHeader
        icon="fa-trash-can"
        eyebrow="Lifecycle · Infrastructure Destroy"
        title="Destroy Infrastructure"
        subtitle="Tear down the AWS resources MultiMinds provisioned. The platform never runs Terraform — it commits a destroy.yml workflow and GitHub Actions runs terraform destroy. The run is observed here read-only, exactly like the Infrastructure pipeline."
        status={status}
        actions={phaseStatus ? <StatusBadge status={phaseStatus} /> : null}
      />
      {children}
    </>
  );
}

function WarningBanner() {
  return (
    <div className="surface mt-3 d-flex align-items-center gap-2" style={{ borderLeft: '3px solid #ef4444' }}>
      <i className="fa-solid fa-triangle-exclamation" style={{ color: '#ef4444' }} />
      <span style={{ fontSize: '.86rem' }}>
        <strong style={{ color: '#ef4444' }}>This operation permanently removes AWS resources.</strong>{' '}
        Destroying runs <code>terraform destroy</code> via GitHub Actions and cannot be undone.
      </span>
    </div>
  );
}

/* ── Prerequisites (pre-flight) ─────────────────────────────────────────────── */

function PrerequisitesCard({ data, projectId }) {
  const items = [
    ['Repository URL', data?.hasRepoUrl],
    ['GitHub token', data?.hasGithubToken],
    ['Terraform configuration', data?.hasTerraform],
  ];
  return (
    <div className="surface mt-3">
      <strong style={{ fontSize: '.92rem' }}>Not ready to destroy yet</strong>
      <p className="text-muted mt-1" style={{ fontSize: '.82rem' }}>
        Destroy needs the same inputs as installation: a repository, a GitHub token and the
        generated Terraform. Provision the infrastructure first (install the pipelines), then
        return here to tear it down.
      </p>
      <ul className="mb-0" style={{ listStyle: 'none', paddingLeft: 0 }}>
        {items.map(([label, ok]) => (
          <li key={label} className="d-flex align-items-center gap-2 py-1" style={{ fontSize: '.84rem' }}>
            <i
              className={`fa-solid ${ok ? 'fa-circle-check' : 'fa-circle-xmark'}`}
              style={{ color: ok ? '#22c55e' : '#ef4444' }}
            />
            {label}
          </li>
        ))}
      </ul>
      {projectId && (
        <Link to={`/projects/${projectId}/settings`} className="boc btn px-3 py-2 mt-3" style={{ fontSize: '.82rem' }}>
          <i className="fa-solid fa-gear me-2" />
          Open project settings
        </Link>
      )}
    </div>
  );
}

/* ── Action + status ────────────────────────────────────────────────────────── */

function ActionCard({ data, inFlight, disabled, onOpen, onRefresh }) {
  const succeeded = data?.succeeded;
  return (
    <div className="surface mt-3 d-flex align-items-center justify-content-between flex-wrap gap-2">
      <div>
        <div className="d-flex align-items-center gap-2">
          <strong style={{ fontSize: '.92rem' }}>Infrastructure</strong>
          {data?.phaseStatus && <StatusBadge status={data.phaseStatus} />}
        </div>
        <div className="text-muted mt-1" style={{ fontSize: '.8rem' }}>
          {succeeded
            ? 'The infrastructure has been destroyed. The project can now be deleted.'
            : inFlight
            ? 'A destroy run is in progress — this view refreshes automatically.'
            : 'Destroying commits destroy.yml and triggers terraform destroy on GitHub Actions.'}
        </div>
      </div>
      <div className="d-flex gap-2">
        {(inFlight || data?.phaseStatus) && (
          <button type="button" className="boc btn px-3 py-2" style={{ fontSize: '.82rem' }} onClick={onRefresh}>
            <i className="fa-solid fa-rotate me-2" />Refresh
          </button>
        )}
        {!succeeded && (
          <button
            type="button"
            className="btn px-3 py-2"
            style={{ fontSize: '.82rem', background: '#ef4444', color: '#fff', opacity: disabled ? 0.55 : 1 }}
            disabled={disabled}
            onClick={onOpen}
          >
            <i className="fa-solid fa-trash-can me-2" />
            {inFlight ? 'Destroying…' : data?.phaseStatus ? 'Destroy again' : 'Destroy Infrastructure'}
          </button>
        )}
      </div>
    </div>
  );
}

function ProvenanceCard({ data }) {
  const rows = [
    ['Branch', data?.branch],
    ['Commit', data?.commitSha ? data.commitSha.slice(0, 10) : null],
    ['Dispatched', data?.dispatched ? 'yes' : 'no'],
  ].filter(([, v]) => v);
  if (!rows.length && !data?.prUrl && !data?.dispatchError) return null;
  return (
    <div className="surface mt-3">
      <div className="text-muted mb-2" style={{ fontSize: '.72rem' }}>destroy.yml installation</div>
      <div className="row g-2">
        {rows.map(([label, value]) => (
          <div className="col-6 col-lg-4" key={label}>
            <div className="surface h-100">
              <div className="text-muted" style={{ fontSize: '.68rem' }}>{label}</div>
              <div style={{ fontSize: '.82rem', wordBreak: 'break-all' }}>{value}</div>
            </div>
          </div>
        ))}
      </div>
      {data?.prUrl && (
        <a href={data.prUrl} target="_blank" rel="noreferrer" className="boc btn px-3 py-2 mt-3" style={{ fontSize: '.8rem' }}>
          <i className="fa-solid fa-code-pull-request me-2" />Open destroy PR
        </a>
      )}
      {data?.dispatchError && (
        <p className="text-muted mt-2 mb-0" style={{ fontSize: '.76rem' }}>
          <i className="fa-solid fa-circle-info me-1" />
          Auto-trigger not confirmed: {data.dispatchError}. Merge the destroy PR and re-run, or
          trigger destroy.yml from the Actions tab.
        </p>
      )}
    </div>
  );
}

function RunCard({ data }) {
  const run = data?.run;
  if (!data?.monitoringAvailable && !run?.found) {
    return (
      <div className="surface mt-3 text-muted" style={{ fontSize: '.82rem' }}>
        <i className="fa-solid fa-satellite-dish me-2" />
        Waiting for the destroy.yml run to appear on GitHub Actions…
      </div>
    );
  }
  if (!run || !run.found) return null;
  const concl = run.conclusion;
  const color = concl === 'success' ? '#22c55e' : concl ? '#ef4444' : '#eab308';
  return (
    <div className="surface mt-3" style={{ borderLeft: `3px solid ${color}` }}>
      <div className="d-flex align-items-center justify-content-between flex-wrap gap-2">
        <div className="d-flex align-items-center gap-2">
          <i className="fa-solid fa-tower-broadcast" style={{ color }} />
          <strong style={{ fontSize: '.9rem' }}>destroy.yml run</strong>
          <StatusBadge status={concl || run.status || 'running'} />
          {run.runNumber != null && (
            <span className="text-muted" style={{ fontSize: '.74rem' }}>#{run.runNumber}</span>
          )}
        </div>
        {run.htmlUrl && (
          <a href={run.htmlUrl} target="_blank" rel="noreferrer" className="boc btn px-3 py-1" style={{ fontSize: '.78rem' }}>
            <i className="fa-solid fa-arrow-up-right-from-square me-2" />Open in GitHub
          </a>
        )}
      </div>
      {(run.currentStep || run.currentJob) && !concl && (
        <div className="text-muted mt-2" style={{ fontSize: '.78rem' }}>
          <i className="fa-solid fa-spinner fa-spin me-2" />
          {run.currentJob}{run.currentStep ? ` · ${run.currentStep}` : ''}
        </div>
      )}
    </div>
  );
}

function PhaseSkeletons() {
  return (
    <div className="mt-3">
      <div className="surface"><Skeleton width="60%" height={14} /></div>
      <div className="surface mt-3"><Skeleton width="40%" height={14} /><Skeleton width="80%" height={12} className="mt-2" /></div>
    </div>
  );
}
