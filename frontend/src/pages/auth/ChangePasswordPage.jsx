import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { useToast } from '@/hooks/useToast';

/**
 * ChangePasswordPage — set a new password (Phase 7).
 *
 * Two modes, same form:
 *   - Forced  (mustChangePassword): an invited engineer who signed in with the
 *     emailed temporary password. ProtectedRoute pins them here until done.
 *   - Voluntary: any user updating their password from settings/profile.
 *
 * On success the auth user is refreshed (must_change_password cleared) and the
 * user is sent to the dashboard, which routes by role.
 */
export default function ChangePasswordPage() {
  const { changePassword, mustChangePassword } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Mirror the backend password policy for instant feedback.
  const validatePassword = (pw) => {
    if (pw.length < 8) return 'New password must be at least 8 characters.';
    if (!/[a-z]/.test(pw) || !/[A-Z]/.test(pw) || !/[0-9]/.test(pw))
      return 'New password must include an uppercase letter, a lowercase letter, and a digit.';
    return '';
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!currentPassword || !newPassword) return setError('Please fill in all fields.');
    const pwError = validatePassword(newPassword);
    if (pwError) return setError(pwError);
    if (newPassword !== confirm) return setError('New passwords do not match.');
    if (newPassword === currentPassword)
      return setError('Your new password must be different from the current one.');
    setError('');
    setLoading(true);
    try {
      await changePassword({ currentPassword, newPassword });
      toast.success('Your password has been updated.');
      navigate('/', { replace: true });
    } catch (err) {
      setError(err?.message || 'Could not update your password. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fade-in d-flex justify-content-center" style={{ padding: '32px 12px' }}>
      <div style={{ width: '100%', maxWidth: 460 }}>
        <div className="text-center mb-3">
          <div
            className="icon-tile mx-auto mb-3"
            style={{ width: 56, height: 56, fontSize: '1.4rem', background: 'rgba(99,102,241,.12)', color: '#6366f1' }}
          >
            <i className="fa-solid fa-shield-halved" />
          </div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: 4 }}>
            {mustChangePassword ? 'Set your password' : 'Change your password'}
          </h1>
          <p style={{ fontSize: '.86rem', color: 'var(--tx3)' }}>
            {mustChangePassword
              ? 'For security, set a new password to replace the temporary one from your invitation email.'
              : 'Update the password you use to sign in.'}
          </p>
        </div>

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
            <label className="form-label-sm">
              {mustChangePassword ? 'Temporary password' : 'Current password'}
            </label>
            <input
              className="oinp mb-3"
              type="password"
              placeholder={mustChangePassword ? 'From your invitation email' : 'Current password'}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
              autoFocus
            />

            <label className="form-label-sm">New password</label>
            <input
              className="oinp mb-3"
              type="password"
              placeholder="Min. 8 chars, incl. upper/lower/number"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
            />

            <label className="form-label-sm">Confirm new password</label>
            <input
              className="oinp mb-3"
              type="password"
              placeholder="Re-enter new password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
            />

            <button className="bgrd btn w-100 py-3 fw-semibold mt-2" disabled={loading}>
              {loading ? (
                <>
                  <span className="spinner me-2" style={{ width: 15, height: 15, borderWidth: 2 }} />
                  Updating…
                </>
              ) : (
                <>
                  Update Password <i className="fa-solid fa-arrow-right ms-1 fa-sm" />
                </>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
