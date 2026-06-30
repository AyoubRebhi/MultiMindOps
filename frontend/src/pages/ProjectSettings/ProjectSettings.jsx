import { useCallback, useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/common/Card';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import EmptyState from '@/components/common/EmptyState';
import Modal from '@/components/common/Modal';
import GithubCredentialForm from '@/components/credentials/GithubCredentialForm';
import AwsCredentialForm from '@/components/credentials/AwsCredentialForm';
import { credentialsApi } from '@/services/api/credentialsApi';
import { projectApi } from '@/services/api/projectApi';
import { useToast } from '@/hooks/useToast';

/**
 * ProjectSettings — project-scoped repository config + DevOps credentials.
 *
 * Reads the aggregated settings (repo URL + branch + per-provider connected/
 * missing status) from GET /api/projects/:id/settings. Credentials are
 * write-only: this surface shows only Connected/Missing + non-secret AWS
 * metadata, never a token or secret key.
 */
export default function ProjectSettings() {
  const { id } = useParams();
  const toast = useToast();

  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSettings(await credentialsApi.getProjectSettings(id));
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const runCredentialAction = async (fn, okMessage) => {
    setBusy(true);
    try {
      await fn();
      await load();
      toast.info(okMessage);
    } catch (err) {
      toast.error(err.message || 'Action failed.');
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <ContentContainer>
        <LoadingSpinner center label="Loading settings…" />
      </ContentContainer>
    );
  }

  if (error || !settings) {
    return (
      <ContentContainer>
        <EmptyState
          icon="fa-triangle-exclamation"
          title="Couldn't load project settings"
          message={error?.message || `No project with id "${id}".`}
          action={
            <Link to={`/projects/${id}`} className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }}>
              Back to Project
            </Link>
          }
        />
      </ContentContainer>
    );
  }

  return (
    <ContentContainer maxWidth={900}>
      <PageHeader
        title="Project Settings"
        subtitle="Repository configuration and deployment credentials for this project."
        breadcrumbs={[
          { label: 'Projects', to: '/projects' },
          { label: 'Project', to: `/projects/${id}` },
          { label: 'Settings' },
        ]}
      />

      <RepositoryCard id={id} settings={settings} onSaved={load} toast={toast} />

      <GithubCredentialForm
        configured={settings.github.configured}
        busy={busy}
        onSave={({ token, label }) =>
          runCredentialAction(
            () => credentialsApi.setGithubCredential(id, { token, label }),
            'GitHub credential saved.'
          )
        }
        onDelete={() =>
          runCredentialAction(
            () => credentialsApi.deleteCredential(id, 'github_pat'),
            'GitHub credential removed.'
          )
        }
      />

      <AwsCredentialForm
        status={settings.aws}
        busy={busy}
        onSave={(fields) =>
          runCredentialAction(
            () => credentialsApi.setAwsCredential(id, fields),
            'AWS credentials saved.'
          )
        }
        onDelete={() =>
          runCredentialAction(
            () => credentialsApi.deleteCredential(id, 'aws_iam'),
            'AWS credentials removed.'
          )
        }
      />

      <DangerZone id={id} toast={toast} />
    </ContentContainer>
  );
}

/* ── Danger zone (delete project — guarded by the destruction rule) ───────── */

function DangerZone({ id, toast }) {
  const navigate = useNavigate();
  const [state, setState] = useState(null);
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let alive = true;
    projectApi
      .deletionState(id)
      .then((s) => alive && setState(s))
      .catch(() => alive && setState(null));
    return () => {
      alive = false;
    };
  }, [id]);

  const deletable = !!state?.deletable;

  async function confirmDelete() {
    setDeleting(true);
    try {
      await projectApi.remove(id);
      toast.success('Project deleted.');
      navigate('/projects');
    } catch (err) {
      // 409 = the deletion guard rejected it (infrastructure still live).
      toast.error(err?.message || 'Could not delete the project.');
      setOpen(false);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Card title="Danger Zone" icon="fa-triangle-exclamation" className="mt-3">
      <p className="text-muted" style={{ fontSize: '.84rem' }}>
        Permanently delete this project and everything it owns (workflows, artifacts, credentials).
        This cannot be undone.
      </p>

      {state && !deletable && (
        <div className="surface mb-3" style={{ borderLeft: '3px solid #eab308' }}>
          <div className="d-flex align-items-center gap-2" style={{ fontSize: '.84rem' }}>
            <i className="fa-solid fa-shield-halved" style={{ color: '#eab308' }} />
            <strong>Deletion blocked — live infrastructure exists.</strong>
          </div>
          <p className="text-muted mb-2 mt-2" style={{ fontSize: '.8rem' }}>
            {state.reason || 'Destroy the infrastructure before deleting the project.'}
          </p>
          <Link to={`/projects/${id}`} className="boc btn px-3 py-1" style={{ fontSize: '.78rem' }}>
            <i className="fa-solid fa-trash-can me-2" />
            Open project to destroy infrastructure
          </Link>
        </div>
      )}

      <button
        type="button"
        className="btn px-3 py-2"
        style={{ fontSize: '.85rem', background: '#ef4444', color: '#fff', opacity: deletable ? 1 : 0.5 }}
        disabled={!deletable}
        onClick={() => setOpen(true)}
        title={deletable ? 'Delete this project' : 'Destroy the infrastructure first'}
      >
        <i className="fa-solid fa-trash-can me-2" />
        Delete Project
      </button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Delete this project?"
        icon="fa-triangle-exclamation"
        footer={
          <>
            <button type="button" className="boc btn px-3 py-2" style={{ fontSize: '.82rem' }} onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn px-3 py-2"
              style={{ fontSize: '.82rem', background: '#ef4444', color: '#fff', opacity: deleting ? 0.6 : 1 }}
              disabled={deleting}
              onClick={confirmDelete}
            >
              {deleting ? <span className="spinner me-2" /> : <i className="fa-solid fa-trash-can me-2" />}
              Delete project
            </button>
          </>
        }
      >
        <p style={{ fontSize: '.86rem' }}>
          This permanently deletes the project and all of its workflows, artifacts and credentials.
          This action cannot be undone.
        </p>
      </Modal>
    </Card>
  );
}

/* ── Repository ──────────────────────────────────────────────────────────── */

function RepositoryCard({ id, settings, onSaved, toast }) {
  const [repositoryUrl, setRepositoryUrl] = useState(settings.repositoryUrl || '');
  const [defaultBranch, setDefaultBranch] = useState(settings.defaultBranch || '');
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await credentialsApi.updateProjectSettings(id, {
        repositoryUrl: repositoryUrl.trim(),
        defaultBranch: defaultBranch.trim(),
      });
      await onSaved();
      toast.info('Repository settings saved.');
    } catch (err) {
      toast.error(err.message || 'Could not save repository settings.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="Repository" icon="fa-code-branch" className="mb-3">
      <div className="row g-3">
        <div className="col-sm-8">
          <label className="form-label-sm">Repository URL</label>
          <input
            className="oinp"
            placeholder="https://github.com/org/repo"
            value={repositoryUrl}
            onChange={(e) => setRepositoryUrl(e.target.value)}
          />
        </div>
        <div className="col-sm-4">
          <label className="form-label-sm">Default Branch</label>
          <input
            className="oinp"
            placeholder="main"
            value={defaultBranch}
            onChange={(e) => setDefaultBranch(e.target.value)}
          />
        </div>
      </div>
      <div className="mt-3">
        <button
          className="bgrd btn px-3 py-2"
          style={{ fontSize: '.85rem' }}
          onClick={save}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Save Repository'}
        </button>
      </div>
    </Card>
  );
}
