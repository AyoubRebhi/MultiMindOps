import { useState } from 'react';
import Modal from '@/components/common/Modal';

/**
 * CreateProjectModal — onboard a repository as a project.
 *
 * Fields: Project Name, Repository URL, Visibility (public/private), and a
 * GitHub Token shown + required only when the repository is private. The token
 * is write-only: it is sent to the backend (encrypted there) and never read
 * back, so it is also dropped from local state as soon as the modal closes.
 *
 * Props:
 *  - open, onClose
 *  - onCreate: async ({ name, description, repositoryUrl, repositoryVisibility, githubToken }) => project
 *  - creating: boolean (disables submit)
 *  - serverError: { message } | null (surfaced from the failed request)
 */
const GITHUB_URL_RE = /^https?:\/\/(www\.)?github\.com\/[^/]+\/[^/]+/i;

export default function CreateProjectModal({
  open,
  onClose,
  onCreate,
  creating = false,
  serverError = null,
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [repositoryUrl, setRepositoryUrl] = useState('');
  const [visibility, setVisibility] = useState('public');
  const [githubToken, setGithubToken] = useState('');
  const [errors, setErrors] = useState({});

  const reset = () => {
    setName('');
    setDescription('');
    setRepositoryUrl('');
    setVisibility('public');
    setGithubToken(''); // never persist the secret past the modal lifecycle
    setErrors({});
  };

  const handleClose = () => {
    reset();
    onClose?.();
  };

  const validate = () => {
    const next = {};
    if (!name.trim()) next.name = 'Project name is required.';
    if (!repositoryUrl.trim()) {
      next.repositoryUrl = 'Repository URL is required.';
    } else if (!GITHUB_URL_RE.test(repositoryUrl.trim())) {
      next.repositoryUrl = 'Enter a valid GitHub repository URL (https://github.com/owner/repo).';
    }
    if (visibility === 'private' && !githubToken.trim()) {
      next.githubToken = 'A GitHub token is required to access a private repository.';
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSubmit = async (e) => {
    e?.preventDefault();
    if (!validate()) return;
    try {
      await onCreate?.({
        name: name.trim(),
        description: description.trim(),
        repositoryUrl: repositoryUrl.trim(),
        repositoryVisibility: visibility,
        githubToken: visibility === 'private' ? githubToken.trim() : '',
      });
      // Success path: parent closes the modal + navigates. Drop the secret now.
      reset();
    } catch {
      // Field-level errors already shown; server error comes via serverError.
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="New Project"
      icon="fa-folder-plus"
      maxWidth={540}
      footer={
        <>
          <button className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={handleClose}>
            Cancel
          </button>
          <button
            className="bgrd btn px-3 py-2"
            style={{ fontSize: '.85rem' }}
            onClick={handleSubmit}
            disabled={creating}
          >
            {creating ? (
              <>
                <span className="spinner me-2" style={{ width: 14, height: 14, borderWidth: 2 }} />
                Creating…
              </>
            ) : (
              <>
                <i className="fa-solid fa-rocket me-2" />
                Create & Analyze
              </>
            )}
          </button>
        </>
      }
    >
      <form onSubmit={handleSubmit}>
        {serverError && (
          <Banner>{serverError.message || 'Could not create the project.'}</Banner>
        )}

        <label className="form-label-sm">Project name</label>
        <input
          className="oinp mb-1"
          type="text"
          placeholder="Payments API"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        <FieldError>{errors.name}</FieldError>

        <label className="form-label-sm mt-2">Repository URL</label>
        <input
          className="oinp mb-1"
          type="text"
          placeholder="https://github.com/owner/repo"
          value={repositoryUrl}
          onChange={(e) => setRepositoryUrl(e.target.value)}
        />
        <FieldError>{errors.repositoryUrl}</FieldError>

        <label className="form-label-sm mt-2">Description (optional)</label>
        <textarea
          className="oinp mb-3"
          rows={2}
          placeholder="What does this service do?"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          style={{ resize: 'vertical' }}
        />

        <label className="form-label-sm">Visibility</label>
        <div className="d-flex gap-2 mb-1">
          <VisibilityOption
            active={visibility === 'public'}
            icon="fa-globe"
            label="Public"
            hint="No token needed"
            onClick={() => setVisibility('public')}
          />
          <VisibilityOption
            active={visibility === 'private'}
            icon="fa-lock"
            label="Private"
            hint="Requires a GitHub token"
            onClick={() => setVisibility('private')}
          />
        </div>

        {visibility === 'private' && (
          <div className="mt-2">
            <label className="form-label-sm">
              GitHub token <span style={{ color: '#f87171' }}>*</span>
            </label>
            <input
              className="oinp mb-1"
              type="password"
              autoComplete="off"
              placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
              value={githubToken}
              onChange={(e) => setGithubToken(e.target.value)}
            />
            <FieldError>{errors.githubToken}</FieldError>
            <p className="mb-0 mt-1 d-flex align-items-center gap-2" style={{ fontSize: '.72rem', color: 'var(--tx3)' }}>
              <i className="fa-solid fa-shield-halved" />
              Stored encrypted. It is never displayed again after you submit.
            </p>
          </div>
        )}
      </form>
    </Modal>
  );
}

function VisibilityOption({ active, icon, label, hint, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="surface text-start"
      style={{
        flex: 1,
        padding: '10px 12px',
        borderRadius: 10,
        cursor: 'pointer',
        border: active ? '1px solid rgba(139,92,246,.5)' : '1px solid var(--bd)',
        background: active ? 'rgba(139,92,246,.12)' : 'var(--sf)',
      }}
    >
      <div className="d-flex align-items-center gap-2" style={{ fontWeight: 600, fontSize: '.85rem' }}>
        <i className={`fa-solid ${icon}`} style={{ color: active ? '#a78bfa' : 'var(--tx3)' }} />
        {label}
      </div>
      <div style={{ fontSize: '.72rem', color: 'var(--tx3)' }}>{hint}</div>
    </button>
  );
}

function FieldError({ children }) {
  if (!children) return null;
  return (
    <div style={{ fontSize: '.74rem', color: '#f87171', marginBottom: 4 }}>
      <i className="fa-solid fa-circle-exclamation me-1" />
      {children}
    </div>
  );
}

function Banner({ children }) {
  return (
    <div
      className="mb-3 d-flex align-items-center gap-2"
      style={{
        fontSize: '.8rem',
        color: '#f87171',
        padding: '8px 12px',
        borderRadius: 10,
        background: 'rgba(248,113,113,.1)',
      }}
    >
      <i className="fa-solid fa-circle-exclamation" />
      {children}
    </div>
  );
}
