import { useEffect, useState } from 'react';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/common/Card';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import AwsCredentialCard from '@/components/aws/AwsCredentialCard';
import { useAwsCredentials } from '@/hooks/useAwsCredentials';
import { awsCredentialsApi } from '@/services/api/awsCredentialsApi';
import { AWS_REGIONS } from '@/utils/constants';

/** A password-style input with an inline show/hide toggle. */
function SecretInput({ value, onChange, placeholder }) {
  const [show, setShow] = useState(false);
  return (
    <div style={{ position: 'relative' }}>
      <input
        className="oinp mono"
        type={show ? 'text' : 'password'}
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        style={{ paddingRight: 40 }}
      />
      <button
        type="button"
        className="key-reveal"
        style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)' }}
        onClick={() => setShow((s) => !s)}
        aria-label={show ? 'Hide' : 'Show'}
      >
        <i className={`fa-regular ${show ? 'fa-eye-slash' : 'fa-eye'}`} />
      </button>
    </div>
  );
}

export default function AwsCredentialsPage() {
  const { data, loading } = useAwsCredentials();
  const [creds, setCreds] = useState(null);
  const [form, setForm] = useState({
    region: 'eu-west-1',
    accessKeyId: '',
    secretAccessKey: '',
    sessionToken: '',
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    if (data) {
      setCreds(data);
      setForm((f) => ({ ...f, region: data.region }));
    }
  }, [data]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    setSaved(false);
    try {
      const updated = await awsCredentialsApi.save(form);
      setCreds(updated);
      setForm((f) => ({ ...f, accessKeyId: '', secretAccessKey: '', sessionToken: '' }));
      setSaved(true);
      setTestResult(null);
      setTimeout(() => setSaved(false), 2500);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await awsCredentialsApi.testConnection();
      setTestResult(res);
    } finally {
      setTesting(false);
    }
  };

  if (loading && !creds) {
    return (
      <ContentContainer>
        <LoadingSpinner center label="Loading AWS credentials…" />
      </ContentContainer>
    );
  }

  return (
    <ContentContainer>
      <PageHeader
        title="AWS Credentials"
        subtitle="Connect AWS so the platform can provision infrastructure on your behalf."
        breadcrumbs={[{ label: 'AWS Credentials' }]}
      />

      <div
        className="mb-4 d-flex align-items-start gap-2"
        style={{
          fontSize: '.8rem',
          color: 'var(--tx2)',
          padding: '12px 14px',
          borderRadius: 12,
          background: 'rgba(139,92,246,.08)',
          border: '1px solid rgba(139,92,246,.2)',
        }}
      >
        <i className="fa-solid fa-shield-halved mt-1" style={{ color: '#a78bfa' }} />
        <span>
          Secrets are encrypted at rest and never shown in plaintext — only the last 4 characters
          are ever revealed. Prefer scoped, least-privilege IAM credentials.
        </span>
      </div>

      <div className="row g-3">
        <div className="col-lg-6">
          <AwsCredentialCard
            credentials={creds}
            onTest={handleTest}
            testing={testing}
            testResult={testResult}
          />
        </div>

        <div className="col-lg-6">
          <Card title="Update Credentials" icon="fa-key">
            {saved && (
              <div
                className="mb-3 d-flex align-items-center gap-2"
                style={{ fontSize: '.82rem', color: '#34d399', padding: '9px 12px', borderRadius: 10, background: 'rgba(52,211,153,.1)' }}
              >
                <i className="fa-solid fa-circle-check" />
                Credentials saved (mock).
              </div>
            )}
            <form onSubmit={handleSave}>
              <label className="form-label-sm">AWS Region</label>
              <select className="oinp mb-3" value={form.region} onChange={set('region')}>
                {AWS_REGIONS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>

              <label className="form-label-sm">AWS Access Key ID</label>
              <input
                className="oinp mono mb-3"
                placeholder="AKIA…"
                value={form.accessKeyId}
                onChange={set('accessKeyId')}
              />

              <label className="form-label-sm">AWS Secret Access Key</label>
              <div className="mb-3">
                <SecretInput value={form.secretAccessKey} onChange={set('secretAccessKey')} placeholder="••••••••••••••••" />
              </div>

              <label className="form-label-sm">
                AWS Session Token <span style={{ color: 'var(--tx3)', fontWeight: 400 }}>(optional)</span>
              </label>
              <div className="mb-3">
                <SecretInput value={form.sessionToken} onChange={set('sessionToken')} placeholder="Temporary session token" />
              </div>

              <button className="bgrd btn w-100 py-2 fw-semibold" disabled={saving}>
                {saving ? (
                  <>
                    <span className="spinner me-2" style={{ width: 14, height: 14, borderWidth: 2 }} />
                    Saving…
                  </>
                ) : (
                  <>
                    <i className="fa-solid fa-floppy-disk me-2" />
                    Save Credentials
                  </>
                )}
              </button>
            </form>
          </Card>
        </div>
      </div>
    </ContentContainer>
  );
}
