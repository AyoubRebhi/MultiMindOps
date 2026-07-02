import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import StatusBadge from '@/components/common/StatusBadge';
import ErrorState from '@/components/common/ErrorState';
import Skeleton from '@/components/common/Skeleton';
import { useRecoveryPhase } from '@/hooks/useWorkflowRun';

/**
 * WorkflowInfrastructureRecoveryPhase — read-only recovery diagnosis for a failed
 * bootstrap (terraform apply failed on GitHub Actions).
 *
 * PURELY DIAGNOSTIC. The backend never runs Terraform (no apply / destroy /
 * import) and never touches AWS — it observes the failed run, classifies the
 * failure, and returns a structured RecoveryReport with recommendations. The
 * recovery actions below are DISABLED placeholders; the engineer decides what to
 * do. This surface only reads + shows that diagnosis.
 *
 * @param {{ workflowId: string, workflow: object }} props
 */
export default function WorkflowInfrastructureRecoveryPhase({ workflowId, workflow }) {
  const projectId = workflow?.projectId;
  const { data, loading, error, refetch } = useRecoveryPhase(projectId, workflowId);

  if (error && !data) {
    return (
      <Shell status="failed">
        <ErrorState title="Couldn't load the recovery analysis" message={error.message} onRetry={refetch} />
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

  const report = data?.report;
  const phaseStatus = data?.phaseStatus || null;

  return (
    <Shell status={phaseStatus || workflow?.status} phaseStatus={phaseStatus}>
      <DiagnosticBanner />

      {!data?.recoveryAvailable ? (
        <NothingToRecoverCard data={data} onRefresh={refetch} />
      ) : (
        <>
          <FailureSummaryCard report={report} onRefresh={refetch} />
          <DetectedResourcesCard report={report} />
          <RecommendationCard report={report} />
          <AvailableActionsCard report={report} />
          {data?.run && <RunCard run={data.run} />}
        </>
      )}
    </Shell>
  );
}

/* ── Layout shell ───────────────────────────────────────────────────────────── */

function Shell({ status, phaseStatus, children }) {
  return (
    <>
      <WorkflowPhaseHeader
        icon="fa-kit-medical"
        eyebrow="Lifecycle · Infrastructure Recovery"
        title="Infrastructure Recovery"
        subtitle="When a bootstrap fails during terraform apply, this surface diagnoses the failure read-only: it classifies the error, detects affected resources, and recommends a recovery. It never runs Terraform and never changes AWS — you decide what to do."
        status={status}
        actions={phaseStatus ? <StatusBadge status={phaseStatus} /> : null}
      />
      {children}
    </>
  );
}

function DiagnosticBanner() {
  return (
    <div className="surface mt-3 d-flex align-items-center gap-2" style={{ borderLeft: '3px solid #38bdf8' }}>
      <i className="fa-solid fa-shield-halved" style={{ color: '#38bdf8' }} />
      <span style={{ fontSize: '.86rem' }}>
        <strong style={{ color: '#38bdf8' }}>Diagnostic only.</strong>{' '}
        This analysis is read-only — it never runs <code>terraform apply</code>,{' '}
        <code>destroy</code>, or <code>import</code>, and makes no changes to AWS.
      </span>
    </div>
  );
}

/* ── No failure / nothing to recover ────────────────────────────────────────── */

function NothingToRecoverCard({ data, onRefresh }) {
  const noToken = data && !data.hasGithubToken;
  return (
    <div className="surface mt-3">
      <div className="d-flex align-items-center justify-content-between flex-wrap gap-2">
        <div className="d-flex align-items-center gap-2">
          <i className="fa-solid fa-circle-check" style={{ color: '#22c55e' }} />
          <strong style={{ fontSize: '.92rem' }}>No failed provisioning to recover</strong>
        </div>
        <button type="button" className="boc btn px-3 py-2" style={{ fontSize: '.82rem' }} onClick={onRefresh}>
          <i className="fa-solid fa-rotate me-2" />Re-check
        </button>
      </div>
      <p className="text-muted mt-2 mb-0" style={{ fontSize: '.82rem' }}>
        {noToken
          ? 'A GitHub token is required to observe the bootstrap run. Add it in project settings, then re-check here after a failed provisioning.'
          : 'The infrastructure pipeline has not failed, so there is nothing to recover. If a bootstrap fails during terraform apply, this surface will show a structured recovery diagnosis.'}
      </p>
    </div>
  );
}

/* ── Failure summary ────────────────────────────────────────────────────────── */

const FAILURE_META = {
  existing_aws_resource: { label: 'Existing AWS resource', icon: 'fa-clone', color: '#eab308' },
  missing_terraform_state: { label: 'Missing Terraform state', icon: 'fa-database', color: '#eab308' },
  invalid_credentials: { label: 'Invalid AWS credentials', icon: 'fa-key', color: '#ef4444' },
  missing_permissions: { label: 'Missing IAM permissions', icon: 'fa-user-lock', color: '#ef4444' },
  terraform_syntax_error: { label: 'Terraform syntax error', icon: 'fa-code', color: '#ef4444' },
  provider_error: { label: 'Provider error', icon: 'fa-plug-circle-xmark', color: '#eab308' },
  aws_api_error: { label: 'AWS API error', icon: 'fa-cloud-bolt', color: '#eab308' },
  unknown: { label: 'Unknown failure', icon: 'fa-circle-question', color: '#94a3b8' },
};

const CONFIDENCE_VARIANT = { high: 'success', medium: 'warning', low: 'pending' };

function FailureSummaryCard({ report, onRefresh }) {
  if (!report) return null;
  const meta = FAILURE_META[report.failureType] || FAILURE_META.unknown;
  return (
    <div className="surface mt-3" style={{ borderLeft: `3px solid ${meta.color}` }}>
      <div className="d-flex align-items-center justify-content-between flex-wrap gap-2">
        <div className="d-flex align-items-center gap-2">
          <i className={`fa-solid ${meta.icon}`} style={{ color: meta.color }} />
          <strong style={{ fontSize: '.95rem' }}>{meta.label}</strong>
          <span className={`badge-pill badge-${CONFIDENCE_VARIANT[report.confidence] || 'pending'}`} style={{ fontSize: '.66rem' }}>
            {report.confidence} confidence
          </span>
          {report.recoverable ? (
            <span className="badge-pill badge-success" style={{ fontSize: '.66rem' }}>
              <i className="fa-solid fa-circle-check" /> recoverable
            </span>
          ) : (
            <span className="badge-pill badge-pending" style={{ fontSize: '.66rem' }}>
              <i className="fa-solid fa-circle-question" /> needs investigation
            </span>
          )}
        </div>
        <button type="button" className="boc btn px-3 py-2" style={{ fontSize: '.82rem' }} onClick={onRefresh}>
          <i className="fa-solid fa-rotate me-2" />Refresh
        </button>
      </div>
      <p className="mt-2 mb-0" style={{ fontSize: '.86rem' }}>{report.rootCause}</p>
      <div className="row g-2 mt-1">
        <SignalChip label="Terraform state" ok={report.terraformStateAvailable}
          okText="remote backend configured" noText="no remote state found" />
        <SignalChip label="Terraform outputs" ok={report.terraformOutputsAvailable}
          okText="generated" noText="not generated" />
      </div>
    </div>
  );
}

function SignalChip({ label, ok, okText, noText }) {
  return (
    <div className="col-12 col-lg-6">
      <div className="surface h-100 d-flex align-items-center gap-2" style={{ fontSize: '.8rem' }}>
        <i className={`fa-solid ${ok ? 'fa-circle-check' : 'fa-circle-xmark'}`} style={{ color: ok ? '#22c55e' : '#94a3b8' }} />
        <span className="text-muted">{label}:</span>
        <span>{ok ? okText : noText}</span>
      </div>
    </div>
  );
}

/* ── Detected resources ─────────────────────────────────────────────────────── */

function DetectedResourcesCard({ report }) {
  const resources = report?.detectedResources || [];
  if (!resources.length) return null;
  return (
    <div className="surface mt-3">
      <div className="text-muted mb-2" style={{ fontSize: '.72rem' }}>
        <i className="fa-solid fa-magnifying-glass me-1" />Detected resources
      </div>
      <ul className="mb-0" style={{ listStyle: 'none', paddingLeft: 0 }}>
        {resources.map((r, i) => (
          <li key={`${r.resourceType}-${r.identifier}-${i}`} className="d-flex align-items-center gap-2 py-1" style={{ fontSize: '.84rem' }}>
            <i className="fa-solid fa-cube text-muted" style={{ fontSize: '.78rem' }} />
            <code style={{ fontSize: '.78rem' }}>{r.resourceType}</code>
            {r.identifier && <span style={{ wordBreak: 'break-all' }}>{r.identifier}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ── Recovery recommendation ────────────────────────────────────────────────── */

function RecommendationCard({ report }) {
  if (!report) return null;
  return (
    <div className="surface mt-3" style={{ borderLeft: '3px solid #7c6cf6' }}>
      <div className="d-flex align-items-center gap-2 mb-2">
        <i className="fa-solid fa-lightbulb" style={{ color: '#7c6cf6' }} />
        <strong style={{ fontSize: '.92rem' }}>Recommended: {report.recommendedActionLabel}</strong>
      </div>
      <p className="text-muted mb-0" style={{ fontSize: '.84rem', whiteSpace: 'pre-line' }}>
        {report.explanation}
      </p>
    </div>
  );
}

/* ── Available actions (disabled placeholders) ──────────────────────────────── */

function AvailableActionsCard({ report }) {
  const actions = report?.availableActions || [];
  if (!actions.length) return null;
  return (
    <div className="surface mt-3">
      <div className="text-muted mb-2" style={{ fontSize: '.72rem' }}>
        <i className="fa-solid fa-wrench me-1" />Recovery actions
        <span className="ms-2" style={{ opacity: 0.7 }}>(coming soon — not enabled yet)</span>
      </div>
      <div className="d-flex flex-wrap gap-2">
        {actions.map((a) => (
          <button
            key={a.id}
            type="button"
            className="btn px-3 py-2"
            title="Recovery execution is not enabled yet — this is a diagnostic preview."
            disabled
            style={{
              fontSize: '.82rem',
              cursor: 'not-allowed',
              opacity: 0.6,
              border: a.recommended ? '1px solid #7c6cf6' : '1px solid var(--bd, rgba(255,255,255,.12))',
              background: a.recommended ? 'rgba(124,108,246,.12)' : 'transparent',
            }}
          >
            <i className={`fa-solid ${ACTION_ICON[a.id] || 'fa-wrench'} me-2`} />
            {a.label}
            {a.recommended && <span className="badge bg-secondary ms-2" style={{ fontSize: '.6rem' }}>recommended</span>}
          </button>
        ))}
      </div>
      <p className="text-muted mb-0 mt-2" style={{ fontSize: '.76rem' }}>
        <i className="fa-solid fa-circle-info me-1" />
        These actions are placeholders. The platform performs no recovery execution yet — use the diagnosis to act manually.
      </p>
    </div>
  );
}

const ACTION_ICON = {
  retry: 'fa-rotate-right',
  import: 'fa-file-import',
  destroy: 'fa-trash-can',
};

/* ── Failed run (read-only observation) ─────────────────────────────────────── */

function RunCard({ run }) {
  if (!run || !run.found) return null;
  const concl = run.conclusion;
  const color = concl === 'success' ? '#22c55e' : concl ? '#ef4444' : '#eab308';
  return (
    <div className="surface mt-3" style={{ borderLeft: `3px solid ${color}` }}>
      <div className="d-flex align-items-center justify-content-between flex-wrap gap-2">
        <div className="d-flex align-items-center gap-2">
          <i className="fa-solid fa-tower-broadcast" style={{ color }} />
          <strong style={{ fontSize: '.9rem' }}>bootstrap.yml run</strong>
          <StatusBadge status={concl || run.status || 'running'} />
          {run.runNumber != null && (
            <span className="text-muted" style={{ fontSize: '.74rem' }}>#{run.runNumber}</span>
          )}
        </div>
        {run.htmlUrl && (
          <a href={run.htmlUrl} target="_blank" rel="noreferrer" className="boc btn px-3 py-1" style={{ fontSize: '.78rem' }}>
            <i className="fa-solid fa-arrow-up-right-from-square me-2" />Open run logs
          </a>
        )}
      </div>
      <p className="text-muted mb-0 mt-2" style={{ fontSize: '.76rem' }}>
        The detailed apply error lives in the GitHub Actions logs — open the run to inspect it before acting.
      </p>
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
