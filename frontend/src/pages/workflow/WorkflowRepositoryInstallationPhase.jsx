import { useState } from 'react';
import { Link } from 'react-router-dom';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import EmptyState from '@/components/common/EmptyState';
import ErrorState from '@/components/common/ErrorState';
import Skeleton from '@/components/common/Skeleton';
import StatusBadge from '@/components/common/StatusBadge';
import Modal from '@/components/common/Modal';
import { useRepositoryInstallationPhase } from '@/hooks/useWorkflowRun';
import { useToast } from '@/hooks/useToast';
import { workflowApi } from '@/services/api/workflowApi';

/**
 * WorkflowRepositoryInstallationPhase — the terminal phase, backed by REAL data.
 * ONE read (GET .../repository-installation) feeds the surface: the installation
 * branch, the commit SHA, the optional Pull Request, the files committed, and the
 * human log lines. Installation is triggered through the backend (POST
 * .../phases/REPOSITORY_INSTALLATION), which performs the safe git flow (clone →
 * dedicated branch → write → commit → push, never force, never onto a protected
 * branch). The frontend never touches the repository.
 *
 * @param {{ workflowId: string, workflow: object, onAdvance?: () => void }} props
 */
export default function WorkflowRepositoryInstallationPhase({ workflowId, workflow, onAdvance }) {
  const projectId = workflow?.projectId;
  const toast = useToast();
  const { data, loading, error, refetch } = useRepositoryInstallationPhase(projectId, workflowId);
  const [installing, setInstalling] = useState(false);
  const [showCredentials, setShowCredentials] = useState(false);

  async function handleInstall() {
    if (!projectId || installing) return;
    setInstalling(true);
    try {
      await workflowApi.runRepositoryInstallationPhase(projectId, workflowId);
      const fresh = await refetch();
      if (fresh?.error) {
        toast.error(fresh.error);
      } else if (fresh?.installed) {
        toast.success('Workflows installed onto the installation branch.');
      } else {
        toast.success('Installation triggered.');
      }
      onAdvance?.();
    } catch (e) {
      toast.error(e?.message || 'Could not install the workflows. Please try again.');
    } finally {
      setInstalling(false);
    }
  }

  /* ── Hard transport failure ──────────────────────────────────────────────── */
  if (error && !data) {
    return (
      <Shell status="failed">
        <ErrorState
          title="Couldn't load the Repository Installation phase"
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

  /* ── Pipelines not generated yet → cannot install ────────────────────────── */
  if (!data || !data.prerequisitesMet) {
    return (
      <Shell status="running">
        <PrerequisitesMissing projectId={projectId} />
      </Shell>
    );
  }

  const failed = data.phaseStatus === 'failed' || (!!data.error && !data.installed);

  /* ── Ready to install (or retry after a failure) ─────────────────────────── */
  if (!data.installed) {
    // Pre-flight: the install service hard-requires a repo URL + a GitHub token.
    // Block the action (and explain why) BEFORE the user clicks, so the backend
    // prerequisite 400 becomes exceptional rather than the first feedback.
    const missing = data.missingRequirements || [];
    const canInstall = missing.length === 0;
    return (
      <Shell status={failed ? 'failed' : 'running'}>
        {failed && <InstallError error={data.error} />}
        <RequirementsPanel data={data} />
        <NotInstalled
          projectId={projectId}
          installing={installing}
          onInstall={handleInstall}
          retry={failed}
          canInstall={canInstall}
          missingRequirements={missing}
          onAddCredentials={() => setShowCredentials(true)}
        />
        <CredentialsModal
          open={showCredentials}
          onClose={() => setShowCredentials(false)}
          missing={missing}
        />
      </Shell>
    );
  }

  /* ── Installed ───────────────────────────────────────────────────────────── */
  return (
    <Shell
      status="completed"
      actions={
        <div className="d-flex gap-2">
          <Link
            to={`/workflows/run/${workflowId}/monitoring`}
            className="bgrd btn px-3 py-2"
            style={{ fontSize: '.82rem' }}
          >
            <i className="fa-solid fa-satellite-dish me-2" />
            Proceed to Monitoring
          </Link>
          <button
            type="button"
            className="boc btn px-3 py-2"
            style={{ fontSize: '.82rem' }}
            disabled={installing}
            onClick={handleInstall}
          >
            {installing ? <span className="spinner me-2" /> : <i className="fa-solid fa-rotate-right me-2" />}
            Re-run install
          </button>
        </div>
      }
    >
      <InstallationSummary data={data} />
      {data.logs.length > 0 && <InstallationLog logs={data.logs} />}
    </Shell>
  );
}

/* ── Layout shell: timeline + phase header + content ───────────────────────── */

function Shell({ status, actions, children }) {
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
        icon="fa-code-branch"
        eyebrow="Phase 8 · Repository Installation"
        title="Repository Installation"
        subtitle="Commit the generated GitHub Actions pipelines (bootstrap.yml + deploy.yml) into your repository. They are written onto a dedicated installation branch — never main/master — so you can review and merge them safely. No application source code is modified."
        status={status}
        actions={actions}
      />
      {children}
    </>
  );
}

/* ── Installation summary ──────────────────────────────────────────────────── */

function InstallationSummary({ data }) {
  const rows = [
    ['Installation branch', data.branch],
    ['Base branch', data.baseBranch],
    ['Commit', data.commitSha ? data.commitSha.slice(0, 12) : null],
    ['Repository', data.repoUrl],
  ].filter(([, v]) => v);

  return (
    <div className="surface mt-3">
      <div className="d-flex align-items-center justify-content-between flex-wrap gap-2">
        <div className="d-flex align-items-center gap-2">
          <i className="fa-solid fa-circle-check" style={{ color: '#22c55e' }} />
          <strong style={{ fontSize: '.92rem' }}>Workflows installed</strong>
          <StatusBadge status="completed" />
          {data.noChanges && (
            <span className="badge bg-secondary" style={{ fontSize: '.7rem' }}>
              <i className="fa-solid fa-equals me-1" />Already up to date
            </span>
          )}
        </div>
        {data.prUrl ? (
          <a
            href={data.prUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="bgrd btn px-3 py-2"
            style={{ fontSize: '.82rem' }}
          >
            <i className="fa-solid fa-code-pull-request me-2" />
            {data.prCreated ? 'View pull request' : 'Open pull request'}
          </a>
        ) : (
          data.prSkippedReason && (
            <span className="text-muted" style={{ fontSize: '.74rem', maxWidth: 360, textAlign: 'right' }}>
              <i className="fa-solid fa-circle-info me-1" />PR not created: {data.prSkippedReason}
            </span>
          )
        )}
      </div>

      <div className="row g-2 mt-2">
        {rows.map(([label, value]) => (
          <div className="col-6 col-lg-3" key={label}>
            <div className="surface h-100">
              <div className="text-muted" style={{ fontSize: '.7rem' }}>{label}</div>
              <div style={{ fontSize: '.82rem', wordBreak: 'break-all', fontFamily: label === 'Commit' ? 'monospace' : undefined }}>
                {value || '—'}
              </div>
            </div>
          </div>
        ))}
      </div>

      {data.files.length > 0 && (
        <div className="mt-3" style={{ fontSize: '.78rem' }}>
          <div className="text-muted mb-1">Committed files</div>
          <div className="d-flex flex-wrap gap-2">
            {data.files.map((f) => (
              <span key={f} className="badge bg-dark" style={{ fontSize: '.7rem' }}>
                <i className="fa-regular fa-file-code me-1" />{f}
              </span>
            ))}
          </div>
        </div>
      )}

      <p className="text-muted mt-3 mb-0" style={{ fontSize: '.74rem' }}>
        Review the branch <code>{data.branch}</code> and merge it into{' '}
        <code>{data.baseBranch}</code> when you&apos;re ready. Add the{' '}
        <code>AWS_ACCESS_KEY_ID</code> / <code>AWS_SECRET_ACCESS_KEY</code> repository
        secrets to enable the pipelines.
      </p>
    </div>
  );
}

/* ── Installation log ──────────────────────────────────────────────────────── */

function InstallationLog({ logs }) {
  return (
    <div className="surface mt-3">
      <div className="d-flex align-items-center gap-2 mb-2">
        <i className="fa-solid fa-terminal" style={{ opacity: 0.7 }} />
        <strong style={{ fontSize: '.88rem' }}>Installation log</strong>
      </div>
      <pre
        className="mb-0"
        style={{
          maxHeight: 320,
          overflow: 'auto',
          background: 'rgba(0,0,0,.35)',
          borderRadius: 8,
          padding: '12px 14px',
          fontSize: '.76rem',
          lineHeight: 1.6,
        }}
      >
        <code>{logs.map((l) => `› ${l}`).join('\n')}</code>
      </pre>
    </div>
  );
}

/* ── States ────────────────────────────────────────────────────────────────── */

function InstallError({ error }) {
  return (
    <div className="surface mt-3" style={{ borderLeft: '3px solid #ef4444' }}>
      <div className="d-flex align-items-center gap-2">
        <i className="fa-solid fa-circle-xmark" style={{ color: '#ef4444' }} />
        <strong style={{ fontSize: '.9rem' }}>Installation failed</strong>
      </div>
      <p className="mb-0 mt-2" style={{ fontSize: '.8rem', color: '#fca5a5' }}>{error}</p>
      <p className="text-muted mb-0 mt-2" style={{ fontSize: '.74rem' }}>
        Nothing was force-pushed and no source files were changed. Fix the issue
        (often a missing/expired GitHub token or insufficient permissions) and try again.
      </p>
    </div>
  );
}

function NotInstalled({
  projectId,
  installing,
  onInstall,
  retry,
  canInstall,
  missingRequirements,
  onAddCredentials,
}) {
  const needsToken = missingRequirements.includes('github_token');
  const needsRepo = missingRequirements.includes('repository_url');
  const blockedMessage = needsToken
    ? 'GitHub Personal Access Token required.'
    : needsRepo
      ? 'A repository URL is required for this project.'
      : 'Installation requirements are missing.';

  return (
    <EmptyState
      icon="fa-code-branch"
      title={retry ? 'Retry installing the pipelines' : 'Install the pipelines into your repository'}
      message="The generated bootstrap.yml and deploy.yml are ready. Installing commits them onto a dedicated branch (multiminds/devops-pipelines) — never main or master — and opens a pull request when possible, so you can review and merge them safely. Only the two .github/workflows files are touched; no application source code is modified, and nothing is force-pushed."
      action={
        <div className="d-flex flex-column align-items-center gap-2">
          {!canInstall && (
            <div style={{ fontSize: '.8rem', color: '#f59e0b' }}>
              <i className="fa-solid fa-triangle-exclamation me-2" />
              {blockedMessage}
            </div>
          )}
          <div className="d-flex gap-2 justify-content-center">
            <button
              type="button"
              className="bgrd btn px-4 py-2"
              style={{ fontSize: '.85rem' }}
              disabled={installing || !canInstall}
              onClick={onInstall}
              title={canInstall ? undefined : 'Add the required credentials before installing'}
            >
              {installing ? (
                <><span className="spinner me-2" />Installing…</>
              ) : (
                <><i className="fa-solid fa-code-branch me-2" />{retry ? 'Retry installation' : 'Install Pipelines'}</>
              )}
            </button>
            {!canInstall ? (
              <button
                type="button"
                className="boc btn px-3 py-2"
                style={{ fontSize: '.85rem' }}
                onClick={onAddCredentials}
              >
                <i className="fa-solid fa-key me-2" />
                Add Credentials
              </button>
            ) : (
              projectId && (
                <Link to={`/projects/${projectId}`} className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }}>
                  <i className="fa-solid fa-folder-open me-2" />
                  Open project
                </Link>
              )
            )}
          </div>
        </div>
      }
    />
  );
}

/* ── Installation requirements checklist (UX pre-flight) ─────────────────────── */

function RequirementsPanel({ data }) {
  const rows = [
    {
      ok: data.hasRepoUrl,
      label: 'Repository URL',
      detail: data.hasRepoUrl
        ? (data.repoUrl || 'Configured on this project')
        : 'No repository URL is configured on this project',
    },
    {
      ok: data.hasGithubToken,
      label: 'GitHub Token',
      detail: data.hasGithubToken
        ? 'Personal Access Token configured'
        : 'GitHub Personal Access Token required (repo scope)',
    },
  ];
  return (
    <div className="surface mt-3">
      <div className="d-flex align-items-center gap-2 mb-2">
        <i className="fa-solid fa-clipboard-check" style={{ opacity: 0.7 }} />
        <strong style={{ fontSize: '.9rem' }}>Requirements</strong>
      </div>
      <div className="d-flex flex-column gap-2">
        {rows.map((r) => (
          <RequirementRow key={r.label} ok={r.ok} label={r.label} detail={r.detail} />
        ))}
      </div>
    </div>
  );
}

function RequirementRow({ ok, label, detail }) {
  return (
    <div className="d-flex align-items-start gap-2">
      <i
        className={`fa-solid ${ok ? 'fa-circle-check' : 'fa-circle-xmark'}`}
        style={{ color: ok ? '#22c55e' : '#ef4444', marginTop: 3 }}
        aria-hidden="true"
      />
      <div>
        <div style={{ fontSize: '.84rem', fontWeight: 600 }}>{label}</div>
        <div className="text-muted" style={{ fontSize: '.74rem', wordBreak: 'break-all' }}>{detail}</div>
      </div>
    </div>
  );
}

/* ── Add Credentials (placeholder — no credential storage here) ──────────────── */

function CredentialsModal({ open, onClose, missing = [] }) {
  const needsToken = missing.includes('github_token');
  return (
    <Modal
      open={open}
      onClose={onClose}
      icon="fa-key"
      title="Add GitHub credentials"
      footer={
        <button type="button" className="boc btn px-3 py-2" style={{ fontSize: '.82rem' }} onClick={onClose}>
          Close
        </button>
      }
    >
      <p style={{ fontSize: '.84rem' }}>
        Installing the pipelines clones and pushes to your repository, so a{' '}
        <strong>GitHub Personal Access Token</strong> is required
        {needsToken ? ' — it is not configured yet.' : '.'} The token needs the{' '}
        <code>repo</code> scope (plus <code>actions:read</code> for workflow monitoring).
      </p>
      <ul className="text-muted" style={{ fontSize: '.78rem', lineHeight: 1.7 }}>
        <li>
          Create one in GitHub under{' '}
          <code>Settings → Developer settings → Personal access tokens</code>.
        </li>
        <li>
          It is stored encrypted per project as the <code>github_pat</code> credential and is
          never shown again.
        </li>
        <li>The token is only read at install time to clone and push the workflow files.</li>
      </ul>
      <div className="surface mt-2" style={{ borderLeft: '3px solid var(--pur)' }}>
        <p className="mb-0 text-muted" style={{ fontSize: '.76rem' }}>
          <i className="fa-solid fa-circle-info me-1" />
          Credential management is coming soon. For now a workspace administrator configures the
          project&apos;s <code>github_pat</code> credential — nothing is stored from this dialog.
        </p>
      </div>
    </Modal>
  );
}

function PrerequisitesMissing({ projectId }) {
  return (
    <EmptyState
      icon="fa-diagram-project"
      title="Generate the pipelines first"
      message="Repository installation commits the generated GitHub Actions pipelines into your repository. Run the GitHub Actions Generation phase first to produce bootstrap.yml and deploy.yml, then come back here to install them."
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

function PhaseSkeletons() {
  return (
    <div className="mt-2">
      <div className="surface mt-2">
        <Skeleton width="30%" height={14} />
        <div className="row g-2 mt-2">
          {[0, 1, 2, 3].map((i) => (
            <div className="col-6 col-lg-3" key={i}>
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
      </div>
    </div>
  );
}
