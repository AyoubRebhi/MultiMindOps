import { useState } from 'react';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import StatusBadge from '@/components/common/StatusBadge';
import ErrorState from '@/components/common/ErrorState';
import Skeleton from '@/components/common/Skeleton';
import Modal from '@/components/common/Modal';
import { useLifecyclePhase } from '@/hooks/useWorkflowRun';
import { useToast } from '@/hooks/useToast';
import { workflowApi } from '@/services/api/workflowApi';

/**
 * WorkflowInfrastructureLifecyclePhase — the final operational dashboard.
 *
 * Aggregates everything the platform already does (destroy, monitoring, recovery,
 * automatic import) into one control surface: infrastructure status, Terraform
 * state, resource inventory, recovery history, immutable lifecycle history, and
 * the Retry Bootstrap / Destroy actions. The backend never runs Terraform —
 * actions dispatch GitHub Actions workflows, observed read-only here. Destroy is
 * guarded behind a two-step confirmation.
 *
 * @param {{ workflowId: string, workflow: object }} props
 */
export default function WorkflowInfrastructureLifecyclePhase({ workflowId, workflow }) {
  const projectId = workflow?.projectId;
  const toast = useToast();
  const { data, loading, error, refetch } = useLifecyclePhase(projectId, workflowId);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(null); // 'retry' | 'destroy' | null

  async function handleRetry() {
    if (!projectId || busy) return;
    setBusy('retry');
    try {
      const res = await workflowApi.retryBootstrap(projectId, workflowId);
      toast.success(res?.message || 'Bootstrap re-dispatched.');
      await refetch();
    } catch (e) {
      toast.error(e?.message || 'Could not retry bootstrap.');
    } finally {
      setBusy(null);
    }
  }

  async function handleDestroy() {
    if (!projectId || busy) return;
    setBusy('destroy');
    try {
      const res = await workflowApi.lifecycleDestroy(projectId, workflowId, {
        confirm: true,
        acknowledgeDataLoss: acknowledged,
      });
      toast.success(res?.message || 'Destroy requested.');
      setConfirmOpen(false);
      setAcknowledged(false);
      await refetch();
    } catch (e) {
      toast.error(e?.message || 'Could not start the destroy.');
    } finally {
      setBusy(null);
    }
  }

  if (error && !data) {
    return (
      <Shell status="failed">
        <ErrorState title="Couldn't load the lifecycle dashboard" message={error.message} onRetry={refetch} />
      </Shell>
    );
  }
  if (loading && !data) {
    return <Shell status={workflow?.status}><PhaseSkeletons /></Shell>;
  }

  return (
    <Shell status={data?.infrastructureStatus} infraStatus={data?.infrastructureStatus}>
      {!data?.canManage && <ReadOnlyBanner />}

      <StatusSection data={data} />
      <TerraformStateSection state={data?.terraformState} />
      <RecoverySection data={data} />
      <ResourcesSection inventory={data?.inventory} />
      <ActionsSection
        data={data}
        busy={busy}
        onRetry={handleRetry}
        onOpenDestroy={() => setConfirmOpen(true)}
        onRefresh={refetch}
      />
      <MonitoringSection data={data} />
      <HistorySection events={data?.lifecycleHistory} />

      <DestroyModal
        open={confirmOpen}
        acknowledged={acknowledged}
        destroying={busy === 'destroy'}
        onAck={setAcknowledged}
        onClose={() => { setConfirmOpen(false); setAcknowledged(false); }}
        onConfirm={handleDestroy}
      />
    </Shell>
  );
}

/* ── Shell ───────────────────────────────────────────────────────────────────── */

function Shell({ status, infraStatus, children }) {
  return (
    <>
      <WorkflowPhaseHeader
        icon="fa-server"
        eyebrow="Lifecycle · Operations"
        title="Infrastructure Lifecycle"
        subtitle="Operate the deployed infrastructure: inspect its state and resources, review recovery history, retry a failed bootstrap, or safely destroy it. The platform never runs Terraform — actions dispatch GitHub Actions and are observed here read-only."
        status={status}
        actions={infraStatus ? <StatusBadge status={infraStatus} /> : null}
      />
      {children}
    </>
  );
}

function ReadOnlyBanner() {
  return (
    <div className="surface mt-3 d-flex align-items-center gap-2" style={{ borderLeft: '3px solid #38bdf8' }}>
      <i className="fa-solid fa-eye" style={{ color: '#38bdf8' }} />
      <span style={{ fontSize: '.86rem' }}>
        <strong style={{ color: '#38bdf8' }}>Read-only access.</strong>{' '}
        You can inspect the infrastructure but not retry or destroy it — that needs engineer or administrator access.
      </span>
    </div>
  );
}

/* ── Infrastructure Status ───────────────────────────────────────────────────── */

const STATUS_META = {
  Healthy: { color: '#22c55e', icon: 'fa-circle-check', text: 'Infrastructure is provisioned and the last bootstrap succeeded.' },
  Failed: { color: '#ef4444', icon: 'fa-circle-xmark', text: 'The last bootstrap failed. Retry or review the recovery analysis.' },
  Destroyed: { color: '#94a3b8', icon: 'fa-ban', text: 'The infrastructure has been destroyed.' },
  Pending: { color: '#eab308', icon: 'fa-hourglass-half', text: 'No bootstrap run observed yet.' },
};

function StatusSection({ data }) {
  const s = data?.infrastructureStatus || 'Pending';
  const meta = STATUS_META[s] || STATUS_META.Pending;
  return (
    <Section title="Infrastructure Status" icon="fa-heart-pulse">
      <div className="surface d-flex align-items-center justify-content-between flex-wrap gap-2" style={{ borderLeft: `3px solid ${meta.color}` }}>
        <div className="d-flex align-items-center gap-3">
          <i className={`fa-solid ${meta.icon}`} style={{ color: meta.color, fontSize: '1.4rem' }} />
          <div>
            <div className="d-flex align-items-center gap-2">
              <strong style={{ fontSize: '1rem' }}>{s}</strong>
              <StatusBadge status={s} />
            </div>
            <div className="text-muted mt-1" style={{ fontSize: '.82rem' }}>{meta.text}</div>
          </div>
        </div>
        {!data?.monitoringAvailable && (
          <span className="text-muted" style={{ fontSize: '.76rem' }}>
            <i className="fa-solid fa-satellite-dish me-1" />Live status needs a GitHub token.
          </span>
        )}
      </div>
    </Section>
  );
}

/* ── Terraform State ─────────────────────────────────────────────────────────── */

function TerraformStateSection({ state }) {
  if (!state) return null;
  const cells = [
    ['Backend', state.backendConfigured ? `${state.backendType || 's3'} (remote)` : 'not configured'],
    ['State bucket', state.stateBucket || '—'],
    ['State key', state.stateKey || '—'],
    ['Workspace', state.workspace || 'default'],
    ['Last apply', fmtTime(state.lastApply)],
    ['Last destroy', fmtTime(state.lastDestroy)],
    ['Managed resources', String(state.managedResourcesCount ?? 0)],
    ['Imported resources', String(state.importedResourcesCount ?? 0)],
    ['Drift', state.driftStatus || 'unavailable'],
  ];
  return (
    <Section title="Terraform State" icon="fa-database">
      <div className="row g-2">
        {cells.map(([label, value]) => (
          <div className="col-6 col-lg-4" key={label}>
            <div className="surface h-100">
              <div className="text-muted" style={{ fontSize: '.68rem' }}>{label}</div>
              <div style={{ fontSize: '.84rem', wordBreak: 'break-all' }}>{value}</div>
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ── Recovery ────────────────────────────────────────────────────────────────── */

function RecoverySection({ data }) {
  const history = data?.recoveryHistory || [];
  const recs = data?.recoveryRecommendations || [];
  return (
    <Section title="Recovery" icon="fa-kit-medical">
      {recs.length > 0 && (
        <div className="surface mb-2" style={{ borderLeft: '3px solid #7c6cf6' }}>
          <div className="d-flex align-items-center gap-2 mb-1" style={{ fontSize: '.84rem' }}>
            <i className="fa-solid fa-lightbulb" style={{ color: '#7c6cf6' }} />
            <strong>Recommendations</strong>
          </div>
          <ul className="mb-0 text-muted" style={{ fontSize: '.82rem' }}>
            {recs.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}
      {history.length === 0 ? (
        <div className="surface text-muted" style={{ fontSize: '.82rem' }}>
          <i className="fa-solid fa-circle-info me-2" />No recovery attempts recorded.
        </div>
      ) : (
        <div className="surface" style={{ overflowX: 'auto' }}>
          <table className="table mb-0" style={{ fontSize: '.8rem' }}>
            <thead>
              <tr className="text-muted">
                <th>When</th><th>Detected issue</th><th>Action taken</th><th>Result</th><th>Duration</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h, i) => (
                <tr key={i}>
                  <td>{fmtTime(h.timestamp)}</td>
                  <td>{h.detectedIssue || '—'}</td>
                  <td>{h.actionTaken || '—'}</td>
                  <td><StatusBadge status={h.status} /></td>
                  <td>{fmtDuration(h.durationMs)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

/* ── Resources inventory ─────────────────────────────────────────────────────── */

function ResourcesSection({ inventory }) {
  const groups = inventory || [];
  return (
    <Section title="Resources" icon="fa-cubes">
      {groups.length === 0 ? (
        <div className="surface text-muted" style={{ fontSize: '.82rem' }}>
          <i className="fa-solid fa-circle-info me-2" />No managed resources found in the generated Terraform.
        </div>
      ) : (
        <div className="row g-2">
          {groups.map((g) => (
            <div className="col-12 col-lg-6" key={g.service}>
              <div className="surface h-100">
                <div className="d-flex align-items-center gap-2 mb-2">
                  <i className="fa-solid fa-layer-group text-muted" style={{ fontSize: '.8rem' }} />
                  <strong style={{ fontSize: '.86rem' }}>{g.service}</strong>
                  <span className="badge bg-secondary" style={{ fontSize: '.62rem' }}>{g.resources.length}</span>
                </div>
                <ul className="mb-0" style={{ listStyle: 'none', paddingLeft: 0 }}>
                  {g.resources.map((r) => (
                    <li key={r.terraformAddress} className="d-flex align-items-center gap-2 py-1" style={{ fontSize: '.8rem' }}>
                      <i className="fa-solid fa-cube text-muted" style={{ fontSize: '.7rem' }} />
                      <code style={{ fontSize: '.74rem' }}>{r.resourceType}</code>
                      <span className="text-muted">·</span>
                      <span>{r.name}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

/* ── Actions ─────────────────────────────────────────────────────────────────── */

function ActionsSection({ data, busy, onRetry, onOpenDestroy, onRefresh }) {
  const canManage = !!data?.canManage;
  const retryOk = !!data?.retryBootstrapAvailable;
  const destroyOk = !!data?.destroyAvailable;
  return (
    <Section title="Actions" icon="fa-bolt">
      <div className="surface d-flex flex-wrap gap-2 align-items-center">
        <button
          type="button"
          className="boc btn px-3 py-2"
          style={{ fontSize: '.82rem', opacity: retryOk && !busy ? 1 : 0.55 }}
          disabled={!retryOk || !!busy}
          onClick={onRetry}
          title={retryOk ? 'Re-dispatch bootstrap.yml' : 'Available only after a failed bootstrap'}
        >
          {busy === 'retry' ? <span className="spinner me-2" /> : <i className="fa-solid fa-rotate-right me-2" />}
          Retry Bootstrap
        </button>

        <button
          type="button"
          className="btn px-3 py-2"
          style={{ fontSize: '.82rem', background: '#ef4444', color: '#fff', opacity: destroyOk && !busy ? 1 : 0.55 }}
          disabled={!destroyOk || !!busy}
          onClick={onOpenDestroy}
          title={data?.destroyBlockReason || 'Destroy the infrastructure'}
        >
          <i className="fa-solid fa-trash-can me-2" />Destroy Infrastructure
        </button>

        <button type="button" className="boc btn px-3 py-2" style={{ fontSize: '.82rem' }} onClick={onRefresh}>
          <i className="fa-solid fa-rotate me-2" />Refresh
        </button>

        {!destroyOk && data?.destroyBlockReason && canManage && (
          <span className="text-muted" style={{ fontSize: '.76rem' }}>
            <i className="fa-solid fa-circle-info me-1" />{data.destroyBlockReason}
          </span>
        )}
      </div>
    </Section>
  );
}

/* ── Monitoring (reuses the same run views as bootstrap/deploy/destroy) ───────── */

function MonitoringSection({ data }) {
  const runs = [
    ['Infrastructure (bootstrap)', data?.bootstrapRun],
    ['Delivery (deploy)', data?.deployRun],
    ['Destroy', data?.destroyRun],
  ].filter(([, r]) => r && r.found);
  if (!runs.length) return null;
  return (
    <Section title="Monitoring" icon="fa-satellite-dish">
      <div className="row g-2">
        {runs.map(([label, run]) => {
          const concl = run.conclusion;
          const color = concl === 'success' ? '#22c55e' : concl ? '#ef4444' : '#eab308';
          return (
            <div className="col-12 col-lg-4" key={label}>
              <div className="surface h-100" style={{ borderLeft: `3px solid ${color}` }}>
                <div className="d-flex align-items-center justify-content-between gap-2">
                  <strong style={{ fontSize: '.82rem' }}>{label}</strong>
                  <StatusBadge status={concl || run.status || 'running'} />
                </div>
                {run.htmlUrl && (
                  <a href={run.htmlUrl} target="_blank" rel="noreferrer" className="text-muted d-inline-block mt-2" style={{ fontSize: '.74rem' }}>
                    <i className="fa-solid fa-arrow-up-right-from-square me-1" />Open run
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Section>
  );
}

/* ── Lifecycle history (immutable) ───────────────────────────────────────────── */

function HistorySection({ events }) {
  const list = events || [];
  if (!list.length) return null;
  return (
    <Section title="Lifecycle History" icon="fa-clock-rotate-left">
      <div className="surface">
        <ul className="mb-0" style={{ listStyle: 'none', paddingLeft: 0 }}>
          {list.map((e, i) => (
            <li key={e.id} className="d-flex flex-wrap align-items-center gap-2 py-1"
                style={{ fontSize: '.8rem', borderTop: i ? '1px solid rgba(255,255,255,.06)' : 'none' }}>
              <StatusBadge status={e.status} />
              <strong>{e.eventType}</strong>
              <span className="text-muted">{e.summary}</span>
              {e.createdAt && (
                <span className="text-muted ms-auto" style={{ fontSize: '.72rem' }}>{fmtTime(e.createdAt)}</span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </Section>
  );
}

/* ── Destroy two-step confirmation ───────────────────────────────────────────── */

function DestroyModal({ open, acknowledged, destroying, onAck, onClose, onConfirm }) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Destroy infrastructure?"
      icon="fa-triangle-exclamation"
      footer={
        <>
          <button type="button" className="boc btn px-3 py-2" style={{ fontSize: '.82rem' }} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn px-3 py-2"
            style={{ fontSize: '.82rem', background: '#ef4444', color: '#fff', opacity: acknowledged && !destroying ? 1 : 0.55 }}
            disabled={!acknowledged || destroying}
            onClick={onConfirm}
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
          <strong>This permanently removes every AWS resource Terraform created.</strong>
        </div>
        <p className="text-muted mb-0 mt-2" style={{ fontSize: '.82rem' }}>
          A <code>destroy.yml</code> workflow is committed and triggered; GitHub Actions runs{' '}
          <code>terraform destroy -auto-approve</code>. This cannot be undone. The run appears under
          Monitoring exactly like bootstrap and deploy.
        </p>
      </div>
      <label className="d-flex align-items-start gap-2" style={{ fontSize: '.84rem', cursor: 'pointer' }}>
        <input type="checkbox" checked={acknowledged} onChange={(e) => onAck(e.target.checked)} style={{ marginTop: 3 }} />
        <span>I understand this permanently destroys the AWS resources for this project.</span>
      </label>
    </Modal>
  );
}

/* ── Shared helpers ──────────────────────────────────────────────────────────── */

function Section({ title, icon, children }) {
  return (
    <div className="mt-3">
      <div className="d-flex align-items-center gap-2 mb-2 text-muted" style={{ fontSize: '.74rem', textTransform: 'uppercase', letterSpacing: '.04em' }}>
        <i className={`fa-solid ${icon}`} />
        <span>{title}</span>
      </div>
      {children}
    </div>
  );
}

function fmtTime(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function fmtDuration(ms) {
  if (ms == null) return '—';
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function PhaseSkeletons() {
  return (
    <div className="mt-3">
      <div className="surface"><Skeleton width="50%" height={14} /></div>
      <div className="surface mt-3"><Skeleton width="70%" height={12} /><Skeleton width="40%" height={12} className="mt-2" /></div>
    </div>
  );
}
