import { useCallback, useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/common/Card';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import EmptyState from '@/components/common/EmptyState';
import GithubCredentialForm from '@/components/credentials/GithubCredentialForm';
import AwsCredentialForm from '@/components/credentials/AwsCredentialForm';
import { credentialsApi } from '@/services/api/credentialsApi';
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
    </ContentContainer>
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
