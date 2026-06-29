import { useState } from 'react';
import Card from '@/components/common/Card';
import CredentialStatusBadge from './CredentialStatusBadge';

/**
 * AwsCredentialForm — create / update / delete a project's AWS credentials.
 *
 * Secrets are WRITE-ONLY. When configured we show only NON-SECRET metadata
 * (region, account name, access-key-id last-4) — the secret access key is never
 * returned by the backend and never rendered here.
 */
export default function AwsCredentialForm({ status, onSave, onDelete, busy }) {
  const configured = !!status?.configured;
  const [accessKeyId, setAccessKeyId] = useState('');
  const [secretAccessKey, setSecretAccessKey] = useState('');
  const [region, setRegion] = useState(status?.region || '');
  const [accountName, setAccountName] = useState(status?.accountName || '');

  const submit = async () => {
    if (!accessKeyId.trim() || !secretAccessKey.trim() || !region.trim()) return;
    await onSave({
      accessKeyId: accessKeyId.trim(),
      secretAccessKey: secretAccessKey.trim(),
      region: region.trim(),
      accountName: accountName.trim() || undefined,
    });
    setAccessKeyId('');
    setSecretAccessKey('');
  };

  return (
    <Card
      title="AWS"
      icon="fa-brands fa-aws"
      className="mb-3"
      action={<CredentialStatusBadge configured={configured} />}
    >
      {configured && (
        <div
          className="d-flex flex-wrap gap-3 mb-3"
          style={{ padding: '10px 14px', background: 'var(--bg3)', borderRadius: 12, fontSize: '.8rem' }}
        >
          <span className="text-muted-3">
            Region: <span style={{ color: 'var(--tx)' }}>{status.region || '—'}</span>
          </span>
          <span className="text-muted-3">
            Account: <span style={{ color: 'var(--tx)' }}>{status.accountName || '—'}</span>
          </span>
          <span className="text-muted-3">
            Access Key: <span className="mono" style={{ color: 'var(--tx)' }}>••••{status.accessKeyIdLast4 || '????'}</span>
          </span>
        </div>
      )}

      <div className="row g-3">
        <div className="col-sm-6">
          <label className="form-label-sm">Access Key ID</label>
          <input
            className="oinp"
            placeholder={configured ? '••••••••••••' : 'AKIA…'}
            value={accessKeyId}
            onChange={(e) => setAccessKeyId(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div className="col-sm-6">
          <label className="form-label-sm">Secret Access Key</label>
          <input
            className="oinp"
            type="password"
            placeholder={configured ? '••••••••••••••••' : ''}
            value={secretAccessKey}
            onChange={(e) => setSecretAccessKey(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div className="col-sm-6">
          <label className="form-label-sm">Region</label>
          <input
            className="oinp"
            placeholder="eu-west-1"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
          />
        </div>
        <div className="col-sm-6">
          <label className="form-label-sm">Account Name (optional)</label>
          <input
            className="oinp"
            placeholder="e.g. production"
            value={accountName}
            onChange={(e) => setAccountName(e.target.value)}
          />
        </div>
      </div>

      <div className="d-flex gap-2 mt-3">
        <button
          className="bgrd btn px-3 py-2"
          style={{ fontSize: '.85rem' }}
          onClick={submit}
          disabled={busy || !accessKeyId.trim() || !secretAccessKey.trim() || !region.trim()}
        >
          {configured ? 'Update Credentials' : 'Connect'}
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
