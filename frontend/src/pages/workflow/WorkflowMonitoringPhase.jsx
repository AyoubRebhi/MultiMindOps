import { useEffect, useState } from 'react';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import ErrorState from '@/components/common/ErrorState';
import Skeleton from '@/components/common/Skeleton';
import StatusBadge from '@/components/common/StatusBadge';
import { useWorkflowMonitoring } from '@/hooks/useWorkflowRun';
import { getStatusMeta } from '@/utils/constants';

/**
 * WorkflowMonitoringPhase — the terminal phase, backed by REAL data.
 *
 * READ-ONLY observation of the two installed GitHub Actions pipelines
 * (bootstrap.yml → Infrastructure, deploy.yml → Delivery). It NEVER triggers,
 * reruns, or cancels a workflow — it only shows each pipeline's latest run
 * (status, conclusion, branch, commit, duration, current step, run URL). The
 * surface polls every 30s (no WebSocket) and offers a manual refresh.
 *
 * @param {{ workflowId: string, workflow: object }} props
 */
export default function WorkflowMonitoringPhase({ workflowId, workflow }) {
  const projectId = workflow?.projectId;
  const { data, loading, error, refetch } = useWorkflowMonitoring(projectId, workflowId);

  /* ── Hard transport failure (no data at all) ─────────────────────────────── */
  if (error && !data) {
    return (
      <Shell status="failed" onRefresh={refetch} refreshing={loading}>
        <ErrorState
          title="Couldn't load Workflow Monitoring"
          message={error.message}
          onRetry={refetch}
        />
      </Shell>
    );
  }

  /* ── First load ──────────────────────────────────────────────────────────── */
  if (loading && !data) {
    return (
      <Shell status={workflow?.status} onRefresh={refetch} refreshing>
        <PhaseSkeletons />
      </Shell>
    );
  }

  if (!data) return null;

  return (
    <Shell status={workflow?.status} onRefresh={refetch} refreshing={loading}>
      {data.error && <MonitoringNotice message={data.error} stale={data.stale} />}

      <div className="row g-3 mt-1">
        <div className="col-12 col-lg-6">
          <PipelineCard pipeline={data.infrastructure} />
        </div>
        <div className="col-12 col-lg-6">
          <PipelineCard pipeline={data.delivery} />
        </div>
      </div>

      <FooterNote fetchedAt={data.fetchedAt} stale={data.stale} repoUrl={data.repoUrl} />
    </Shell>
  );
}

/* ── Layout shell ──────────────────────────────────────────────────────────── */

function Shell({ status, onRefresh, refreshing, children }) {
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
          cicd: 'completed',
        }}
      />
      <WorkflowPhaseHeader
        icon="fa-satellite-dish"
        eyebrow="Phase 9 · Workflow Monitoring"
        title="Workflow Monitoring"
        subtitle="Observe the installed GitHub Actions pipelines as they run. This view is read-only — it never triggers, reruns, or cancels a workflow. The Infrastructure pipeline (bootstrap.yml) provisions and first-deploys; the Delivery pipeline (deploy.yml) ships on every push. Status refreshes automatically every 30 seconds."
        status={status}
        actions={
          <button
            type="button"
            className="boc btn px-3 py-2"
            style={{ fontSize: '.82rem' }}
            disabled={refreshing}
            onClick={onRefresh}
          >
            {refreshing ? <span className="spinner me-2" /> : <i className="fa-solid fa-rotate-right me-2" />}
            Refresh
          </button>
        }
      />
      {children}
    </>
  );
}

/* ── Pipeline card ─────────────────────────────────────────────────────────── */

function PipelineCard({ pipeline: p }) {
  const icon = p.kind === 'bootstrap' ? 'fa-server' : 'fa-rocket';
  const statusKeyword = runStatusKeyword(p);
  const meta = getStatusMeta(statusKeyword);
  const liveDuration = useLiveDuration(p);

  return (
    <div className="surface h-100 d-flex flex-column">
      <div className="d-flex align-items-center justify-content-between gap-2">
        <div className="d-flex align-items-center gap-2">
          <i className={`fa-solid ${icon}`} style={{ opacity: 0.8 }} />
          <strong style={{ fontSize: '.92rem' }}>{p.name}</strong>
        </div>
        <StatusBadge status={statusKeyword} />
      </div>
      <div className="text-muted mt-1" style={{ fontSize: '.72rem', fontFamily: 'monospace' }}>
        {p.workflowFile}
      </div>

      {/* Per-pipeline failure (token/permission/etc.) */}
      {!p.available && p.error && (
        <p className="mt-2 mb-0" style={{ fontSize: '.78rem', color: '#fca5a5' }}>
          <i className="fa-solid fa-triangle-exclamation me-1" />
          {p.error}
        </p>
      )}

      {/* No runs yet */}
      {p.available && !p.found && (
        <div className="mt-3" style={{ fontSize: '.82rem' }}>
          <i className="fa-regular fa-clock me-2" style={{ opacity: 0.7 }} />
          No runs yet. This pipeline hasn&apos;t been executed on GitHub Actions.
        </div>
      )}

      {/* A run exists */}
      {p.available && p.found && (
        <>
          <div className="d-flex align-items-center gap-2 mt-3" style={{ fontSize: '1rem' }}>
            <i className={`fa-solid ${meta.icon}`} />
            <span style={{ fontWeight: 600 }}>{meta.label}</span>
            {typeof p.runNumber === 'number' && (
              <span className="text-muted" style={{ fontSize: '.74rem' }}>· run #{p.runNumber}</span>
            )}
          </div>

          {p.currentStep && statusKeyword === 'running' && (
            <div className="mt-2" style={{ fontSize: '.82rem' }}>
              <span className="text-muted" style={{ fontSize: '.72rem' }}>Current step</span>
              <div>
                <i className="fa-solid fa-gears me-2" style={{ opacity: 0.7 }} />
                <code>{p.currentStep}</code>
                {p.currentJob && (
                  <span className="text-muted" style={{ fontSize: '.72rem' }}> · {p.currentJob}</span>
                )}
              </div>
            </div>
          )}

          <div className="row g-2 mt-2">
            <Field label="Duration" value={formatDuration(liveDuration)} mono />
            <Field label="Branch" value={p.branch} mono />
            <Field label="Commit" value={p.commitSha ? p.commitSha.slice(0, 7) : null} mono />
            <Field label="Trigger" value={p.event} />
            <Field label="Actor" value={p.actor} />
            <Field label="Conclusion" value={p.conclusion || (p.status !== 'completed' ? '—' : null)} />
          </div>

          <div className="d-flex flex-wrap gap-2 mt-auto pt-3">
            {p.htmlUrl && (
              <a
                href={p.htmlUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="bgrd btn px-3 py-2"
                style={{ fontSize: '.8rem' }}
              >
                <i className="fa-brands fa-github me-2" />Open in GitHub
              </a>
            )}
            {p.workflowUrl && (
              <a
                href={p.workflowUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="boc btn px-3 py-2"
                style={{ fontSize: '.8rem' }}
              >
                <i className="fa-solid fa-list me-2" />All runs
              </a>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Field({ label, value, mono }) {
  return (
    <div className="col-6 col-xl-4">
      <div className="surface h-100">
        <div className="text-muted" style={{ fontSize: '.68rem' }}>{label}</div>
        <div style={{ fontSize: '.8rem', wordBreak: 'break-all', fontFamily: mono ? 'monospace' : undefined }}>
          {value || '—'}
        </div>
      </div>
    </div>
  );
}

/* ── Notices ───────────────────────────────────────────────────────────────── */

function MonitoringNotice({ message, stale }) {
  return (
    <div className="surface mt-3" style={{ borderLeft: '3px solid #f59e0b' }}>
      <div className="d-flex align-items-center gap-2">
        <i className="fa-solid fa-triangle-exclamation" style={{ color: '#f59e0b' }} />
        <strong style={{ fontSize: '.86rem' }}>
          {stale ? 'Showing last-known status' : 'Monitoring degraded'}
        </strong>
      </div>
      <p className="mb-0 mt-2 text-muted" style={{ fontSize: '.78rem' }}>{message}</p>
    </div>
  );
}

function FooterNote({ fetchedAt, stale, repoUrl }) {
  return (
    <p className="text-muted mt-3 mb-0" style={{ fontSize: '.72rem' }}>
      <i className="fa-solid fa-circle-info me-1" />
      Read-only view — MultiMinds observes these runs but never triggers, reruns, or cancels them.
      {repoUrl && <> Repository: <code>{repoUrl}</code>.</>}
      {fetchedAt && (
        <> {stale ? 'Last successful update' : 'Updated'}{' '}
          {new Date(fetchedAt).toLocaleTimeString()} · auto-refresh every 30s.
        </>
      )}
    </p>
  );
}

function PhaseSkeletons() {
  return (
    <div className="row g-3 mt-1">
      {[0, 1].map((i) => (
        <div className="col-12 col-lg-6" key={i}>
          <div className="surface">
            <Skeleton width="40%" height={14} />
            <Skeleton width="60%" height={10} className="mt-2" />
            <div className="row g-2 mt-3">
              {[0, 1, 2, 3].map((j) => (
                <div className="col-6" key={j}>
                  <div className="surface">
                    <Skeleton width="50%" height={10} />
                    <Skeleton width="80%" height={14} className="mt-2" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Helpers ───────────────────────────────────────────────────────────────── */

/** Map a GitHub run's status+conclusion to a STATUS_META keyword (badge color). */
function runStatusKeyword(p) {
  if (!p.found) return 'not_started';
  if (p.status && p.status !== 'completed') {
    return p.status === 'queued' ? 'queued' : 'running';
  }
  const c = (p.conclusion || '').toLowerCase();
  if (c === 'success') return 'succeeded';
  if (c === 'failure' || c === 'startup_failure' || c === 'timed_out') return 'failed';
  if (c === 'cancelled') return 'cancelled';
  return c || 'completed';
}

/** Human duration: 56s · 2m 10s · 1h 03m. */
function formatDuration(seconds) {
  if (seconds == null || seconds < 0) return null;
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rs = s % 60;
  if (m < 60) return `${m}m ${String(rs).padStart(2, '0')}s`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return `${h}h ${String(rm).padStart(2, '0')}m`;
}

/**
 * For a still-running pipeline, tick the duration locally (1s) from startedAt so
 * the timer advances between 30s polls. For a finished run, just use the
 * backend-computed duration (no ticker mounted).
 */
function useLiveDuration(p) {
  const running = p.found && p.status && p.status !== 'completed' && !!p.startedAt;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);
  if (!running) return p.durationSeconds;
  const started = new Date(p.startedAt).getTime();
  if (Number.isNaN(started)) return p.durationSeconds;
  return Math.max(0, Math.floor((now - started) / 1000));
}
