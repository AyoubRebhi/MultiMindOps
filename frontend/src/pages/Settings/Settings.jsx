import { useState } from 'react';
import { Link } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/common/Card';
import { useTheme } from '@/hooks/useTheme';
import { useAuth } from '@/hooks/useAuth';
import { useToast } from '@/hooks/useToast';
import { settingsApi } from '@/services/api/settingsApi';
import { getRoleMeta } from '@/utils/constants';

/**
 * Settings — user self-service profile + password (real backend) and the
 * appearance toggle. DevOps credentials (GitHub/AWS) are deliberately NOT here:
 * they belong to a Project (see Project → Settings), never the global user.
 *
 * `Role` is read-only — it is the global workspace role that gates admin
 * surfaces, so self-editing it would be a privilege escalation. Email changes
 * require the current password (re-auth) enforced by the backend.
 */
export default function Settings() {
  const { theme, setTheme } = useTheme();
  const { user, refreshUser } = useAuth();
  const toast = useToast();

  return (
    <ContentContainer maxWidth={900}>
      <PageHeader
        title="Settings"
        subtitle="Manage your profile, password and appearance."
        breadcrumbs={[{ label: 'Settings' }]}
      />

      <ProfileCard user={user} refreshUser={refreshUser} toast={toast} />
      <PasswordCard toast={toast} />
      <AppearanceCard theme={theme} setTheme={setTheme} />

      {/* DevOps credentials live on the Project, not the user. */}
      <Card title="DevOps Credentials" icon="fa-key">
        <p className="form-help" style={{ marginTop: 0 }}>
          GitHub and AWS credentials are managed per project — different projects can
          use different repositories and cloud accounts.
        </p>
        <Link to="/projects" className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }}>
          <i className="fa-solid fa-folder-open me-2" />
          Go to Projects
        </Link>
      </Card>
    </ContentContainer>
  );
}

/* ── Profile ─────────────────────────────────────────────────────────────── */

function ProfileCard({ user, refreshUser, toast }) {
  const [fullName, setFullName] = useState(user?.name || '');
  const [email, setEmail] = useState(user?.email || '');
  const [currentPassword, setCurrentPassword] = useState('');
  const [saving, setSaving] = useState(false);

  const originalEmail = user?.email || '';
  const emailChanged = email.trim().toLowerCase() !== originalEmail.toLowerCase();

  const handleSave = async () => {
    if (emailChanged && !currentPassword) {
      toast.error('Enter your current password to change your email.');
      return;
    }
    setSaving(true);
    try {
      await settingsApi.updateProfile({
        displayName: fullName,
        email: email.trim(),
        currentPassword: emailChanged ? currentPassword : undefined,
      });
      await refreshUser();
      setCurrentPassword('');
      toast.info('Profile updated.');
    } catch (err) {
      toast.error(err.message || 'Could not update profile.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="Profile" icon="fa-user" className="mb-3">
      <div className="row g-3">
        <div className="col-sm-6">
          <label className="form-label-sm">Full name</label>
          <input className="oinp" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </div>
        <div className="col-sm-6">
          <label className="form-label-sm">Email</label>
          <input
            className="oinp"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="col-sm-6">
          <label className="form-label-sm">Role</label>
          <input className="oinp" value={getRoleMeta(user?.role).label} readOnly />
          <p className="form-help">Your workspace role is managed by an administrator.</p>
        </div>
        {emailChanged && (
          <div className="col-sm-6">
            <label className="form-label-sm">Current password</label>
            <input
              className="oinp"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
            />
            <p className="form-help">Required to change your email.</p>
          </div>
        )}
      </div>
      <div className="mt-3">
        <button
          className="bgrd btn px-3 py-2"
          style={{ fontSize: '.85rem' }}
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Save Changes'}
        </button>
      </div>
    </Card>
  );
}

/* ── Password ────────────────────────────────────────────────────────────── */

function PasswordCard({ toast }) {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [saving, setSaving] = useState(false);

  const handleChange = async () => {
    if (newPassword !== confirm) {
      toast.error('New password and confirmation do not match.');
      return;
    }
    if (newPassword.length < 8) {
      toast.error('New password must be at least 8 characters.');
      return;
    }
    setSaving(true);
    try {
      await settingsApi.changePassword({ currentPassword, newPassword });
      setCurrentPassword('');
      setNewPassword('');
      setConfirm('');
      toast.info('Password changed.');
    } catch (err) {
      toast.error(err.message || 'Could not change password.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="Password" icon="fa-lock" className="mb-3">
      <div className="row g-3">
        <div className="col-sm-4">
          <label className="form-label-sm">Current password</label>
          <input
            className="oinp"
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            autoComplete="current-password"
          />
        </div>
        <div className="col-sm-4">
          <label className="form-label-sm">New password</label>
          <input
            className="oinp"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            autoComplete="new-password"
          />
        </div>
        <div className="col-sm-4">
          <label className="form-label-sm">Confirm new password</label>
          <input
            className="oinp"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
          />
        </div>
      </div>
      <p className="form-help">
        At least 8 characters with one uppercase letter, one lowercase letter, and one digit.
      </p>
      <div className="mt-2">
        <button
          className="bgrd btn px-3 py-2"
          style={{ fontSize: '.85rem' }}
          onClick={handleChange}
          disabled={saving || !currentPassword || !newPassword}
        >
          {saving ? 'Updating…' : 'Change Password'}
        </button>
      </div>
    </Card>
  );
}

/* ── Appearance ──────────────────────────────────────────────────────────── */

function AppearanceCard({ theme, setTheme }) {
  return (
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
  );
}
