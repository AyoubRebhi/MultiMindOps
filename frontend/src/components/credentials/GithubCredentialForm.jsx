import { useState } from 'react';
import Card from '@/components/common/Card';
import CredentialStatusBadge from './CredentialStatusBadge';

/**
 * GithubCredentialForm — add / replace / delete a project's GitHub PAT.
 *
 * The token is WRITE-ONLY: when one is configured we show a masked placeholder,
 * never the value. Required scopes are documented inline. Used automatically by
 * repository installation + workflow monitoring once set.
 */
export default function GithubCredentialForm({ configured, onSave, onDelete, busy }) {
  const [token, setToken] = useState('');
  const [label, setLabel] = useState('');

  const submit = async () => {
    if (!token.trim()) return;
    await onSave({ token: token.trim(), label: label.trim() || undefined });
    setToken('');
    setLabel('');
  };

  return (
    <Card
      title="GitHub"
      icon="fa-brands fa-github"
      className="mb-3"
      action={<CredentialStatusBadge configured={configured} />}
    >
      <p className="form-help" style={{ marginTop: 0 }}>
        Personal Access Token with scopes: <code>repo</code>, <code>workflow</code>,{' '}
        <code>actions:read</code>.
      </p>

      <div className="row g-3">
        <div className="col-sm-7">
          <label className="form-label-sm">Personal Access Token</label>
          <input
            className="oinp"
            type="password"
            placeholder={configured ? '••••••••••••••••' : 'ghp_…'}
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div className="col-sm-5">
          <label className="form-label-sm">Label (optional)</label>
          <input
            className="oinp"
            placeholder="e.g. CI token"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
        </div>
      </div>

      <div className="d-flex gap-2 mt-3">
        <button
          className="bgrd btn px-3 py-2"
          style={{ fontSize: '.85rem' }}
          onClick={submit}
          disabled={busy || !token.trim()}
        >
          {configured ? 'Replace Token' : 'Connect'}
        </button>
        {configured && (
          <button
            className="boc btn px-3 py-2"
            style={{ fontSize: '.85rem' }}
            onClick={onDelete}
            disabled={busy}
          >
            <i className="fa-regular fa-trash-can me-2" />
            Delete
          </button>
        )}
      </div>
    </Card>
  );
}
