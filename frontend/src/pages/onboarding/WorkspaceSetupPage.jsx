import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Stepper from '@/components/common/Stepper';
import { useAuth } from '@/hooks/useAuth';
import { workspaceApi } from '@/services/api/workspaceApi';
import { AWS_REGIONS } from '@/utils/constants';

const STEPS = ['Account', 'Workspace', 'AWS Setup', 'Complete'];

/**
 * WorkspaceSetupPage — Admin onboarding: name the workspace and pick a default
 * AWS region. Shows the onboarding stepper; on success advances to "Complete".
 */
export default function WorkspaceSetupPage() {
  const navigate = useNavigate();
  const { updateUser } = useAuth();
  const [form, setForm] = useState({
    name: '',
    company: '',
    description: '',
    region: 'eu-west-1',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [created, setCreated] = useState(false);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return setError('Workspace name is required.');
    setError('');
    setLoading(true);
    try {
      const ws = await workspaceApi.create(form);
      updateUser({ workspaceId: ws.id, workspaceName: ws.name });
      setCreated(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="text-center mb-2">
        <h1 style={{ fontSize: '1.6rem', fontWeight: 700, marginBottom: 4 }}>
          {created ? 'Workspace ready 🎉' : 'Set up your workspace'}
        </h1>
        <p style={{ fontSize: '.88rem', color: 'var(--tx3)' }}>
          {created
            ? 'Your workspace has been created. Next, connect AWS to start provisioning.'
            : 'Tell us about your team so we can tailor your cloud workspace.'}
        </p>
      </div>

      <Stepper steps={STEPS} current={created ? 3 : 1} />

      {created ? (
        <div className="surface text-center">
          <div
            className="icon-tile mx-auto mb-3"
            style={{ width: 56, height: 56, fontSize: '1.4rem', background: 'rgba(52,211,153,.12)', color: '#34d399' }}
          >
            <i className="fa-solid fa-circle-check" />
          </div>
          <div style={{ fontWeight: 700, fontSize: '1.05rem', marginBottom: 4 }}>{form.name}</div>
          <div style={{ fontSize: '.84rem', color: 'var(--tx3)', marginBottom: 20 }}>
            Default region · {form.region}
          </div>
          <div className="d-flex gap-2 justify-content-center flex-wrap">
            <button
              className="bgrd btn px-4 py-2"
              style={{ fontSize: '.88rem' }}
              onClick={() => navigate('/aws-credentials')}
            >
              <i className="fa-brands fa-aws me-2" />
              Connect AWS
            </button>
            <button className="boc btn px-4 py-2" style={{ fontSize: '.88rem' }} onClick={() => navigate('/')}>
              Skip to dashboard
            </button>
          </div>
        </div>
      ) : (
        <div className="surface">
          {error && (
            <div
              className="mb-3 d-flex align-items-center gap-2"
              style={{ fontSize: '.82rem', color: '#f87171', padding: '9px 12px', borderRadius: 10, background: 'rgba(248,113,113,.1)' }}
            >
              <i className="fa-solid fa-circle-exclamation" />
              {error}
            </div>
          )}
          <form onSubmit={handleSubmit}>
            <label className="form-label-sm">Workspace name</label>
            <input className="oinp mb-3" placeholder="e.g. CloudForge HQ" value={form.name} onChange={set('name')} autoFocus />

            <label className="form-label-sm">Company name</label>
            <input className="oinp mb-3" placeholder="e.g. CloudForge Inc." value={form.company} onChange={set('company')} />

            <label className="form-label-sm">Description</label>
            <textarea
              className="oinp mb-3"
              rows={3}
              placeholder="What will this workspace be used for?"
              value={form.description}
              onChange={set('description')}
              style={{ resize: 'vertical' }}
            />

            <label className="form-label-sm">Default AWS region</label>
            <select className="oinp mb-3" value={form.region} onChange={set('region')}>
              {AWS_REGIONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>

            <button className="bgrd btn w-100 py-3 fw-semibold mt-2" disabled={loading}>
              {loading ? (
                <>
                  <span className="spinner me-2" style={{ width: 15, height: 15, borderWidth: 2 }} />
                  Creating workspace…
                </>
              ) : (
                <>
                  Create Workspace <i className="fa-solid fa-arrow-right ms-1 fa-sm" />
                </>
              )}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
