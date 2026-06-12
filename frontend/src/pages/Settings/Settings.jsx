import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/common/Card';
import ProviderBadge from '@/components/common/ProviderBadge';
import { useTheme } from '@/hooks/useTheme';
import { useAuth } from '@/hooks/useAuth';
import { getRoleMeta } from '@/utils/constants';

const CLOUD_CONNECTIONS = [
  { provider: 'aws', status: 'connected', detail: '2 accounts · eu-west-1, us-east-1' },
  { provider: 'gcp', status: 'connected', detail: '1 project · europe-west1' },
  { provider: 'azure', status: 'disconnected', detail: 'Not connected' },
];

/**
 * Settings — placeholder workspace settings. The theme toggle is wired to the
 * real ThemeContext; everything else is static UI awaiting backend wiring.
 */
export default function Settings() {
  const { theme, setTheme } = useTheme();
  const { user } = useAuth();

  return (
    <ContentContainer maxWidth={900}>
      <PageHeader
        title="Settings"
        subtitle="Manage your profile, appearance and cloud connections."
        breadcrumbs={[{ label: 'Settings' }]}
      />

      {/* Profile */}
      <Card title="Profile" icon="fa-user" className="mb-3">
        <div className="row g-3">
          <div className="col-sm-6">
            <label className="form-label-sm">Full name</label>
            <input className="oinp" defaultValue={user.name} />
          </div>
          <div className="col-sm-6">
            <label className="form-label-sm">Email</label>
            <input className="oinp" type="email" defaultValue={user.email} />
          </div>
          <div className="col-sm-6">
            <label className="form-label-sm">Role</label>
            <input className="oinp" defaultValue={getRoleMeta(user.role).label} readOnly />
          </div>
          <div className="col-sm-6">
            <label className="form-label-sm">Default region</label>
            <input className="oinp" defaultValue="eu-west-1" />
          </div>
        </div>
        <div className="mt-3">
          <button className="bgrd btn px-3 py-2" style={{ fontSize: '.85rem' }}>
            Save Changes
          </button>
        </div>
      </Card>

      {/* Appearance */}
      <Card title="Appearance" icon="fa-palette" className="mb-3">
        <label className="form-label-sm">Theme</label>
        <div className="d-flex gap-2">
          {[
            { key: 'dark', label: 'Dark', icon: 'fa-moon' },
            { key: 'light', label: 'Light', icon: 'fa-sun' },
          ].map((opt) => (
            <button
              key={opt.key}
              className="boc btn px-3 py-2"
              style={{
                fontSize: '.85rem',
                borderRadius: 10,
                background: theme === opt.key ? 'rgba(139,92,246,.15)' : 'var(--sf)',
                color: theme === opt.key ? '#a78bfa' : 'var(--tx2)',
                borderColor: theme === opt.key ? 'rgba(139,92,246,.3)' : 'var(--bd)',
              }}
              onClick={() => setTheme(opt.key)}
            >
              <i className={`fa-solid ${opt.icon} me-2`} />
              {opt.label}
            </button>
          ))}
        </div>
        <p className="form-help">Applies instantly and is remembered on this device.</p>
      </Card>

      {/* Cloud connections */}
      <Card title="Cloud Connections" icon="fa-cloud" className="mb-3">
        <div className="d-flex flex-column gap-2">
          {CLOUD_CONNECTIONS.map((c) => (
            <div
              key={c.provider}
              className="d-flex align-items-center justify-content-between"
              style={{
                padding: '12px 14px',
                background: 'var(--bg3)',
                borderRadius: 12,
              }}
            >
              <div className="d-flex align-items-center gap-3">
                <ProviderBadge provider={c.provider} />
                <span style={{ fontSize: '.8rem', color: 'var(--tx3)' }}>{c.detail}</span>
              </div>
              {c.status === 'connected' ? (
                <span className="badge-pill badge-success">
                  <span className="dot" /> Connected
                </span>
              ) : (
                <button className="boc btn px-3 py-1" style={{ fontSize: '.78rem', borderRadius: 10 }}>
                  Connect
                </button>
              )}
            </div>
          ))}
        </div>
      </Card>

      {/* API access */}
      <Card title="API Access" icon="fa-key">
        <label className="form-label-sm">Platform API key</label>
        <div className="d-flex gap-2">
          <input className="oinp" readOnly value="cf_live_••••••••••••••••3a9f" style={{ flex: 1 }} />
          <button className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }}>
            <i className="fa-regular fa-copy me-2" />
            Copy
          </button>
        </div>
        <p className="form-help">
          Used to authenticate the backend integration once APIs are connected.
        </p>
      </Card>
    </ContentContainer>
  );
}
