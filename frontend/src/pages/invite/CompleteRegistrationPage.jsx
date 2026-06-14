import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Stepper from '@/components/common/Stepper';
import { authApi } from '@/services/api/authApi';

const STEPS = ['Invitation', 'Your details', 'Done'];

/**
 * CompleteRegistrationPage — invited engineer sets their name + password.
 * On success, redirects to the Sign In page (per the journey spec).
 */
export default function CompleteRegistrationPage() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    firstName: '',
    lastName: '',
    password: '',
    confirm: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  // Mirror the backend password policy for instant feedback.
  const validatePassword = (pw) => {
    if (pw.length < 8) return 'Password must be at least 8 characters.';
    if (!/[a-z]/.test(pw) || !/[A-Z]/.test(pw) || !/[0-9]/.test(pw))
      return 'Password must include an uppercase letter, a lowercase letter, and a digit.';
    return '';
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const { firstName, lastName, password, confirm } = form;
    if (!firstName || !lastName || !password) return setError('Please fill in all fields.');
    const pwError = validatePassword(password);
    if (pwError) return setError(pwError);
    if (password !== confirm) return setError('Passwords do not match.');
    setError('');
    setLoading(true);
    try {
      await authApi.acceptInvitation(token, {
        password,
        displayName: `${firstName} ${lastName}`.trim(),
      });
      setDone(true);
      // Per the product journey, the engineer signs in with their new password.
      setTimeout(() => navigate('/auth/signin'), 1800);
    } catch (err) {
      setError(err?.message || 'Could not complete registration. The invitation may have expired.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fade-in">
      <div className="text-center mb-2">
        <h1 style={{ fontSize: '1.6rem', fontWeight: 700, marginBottom: 4 }}>
          {done ? 'All set!' : 'Complete your registration'}
        </h1>
        <p style={{ fontSize: '.88rem', color: 'var(--tx3)' }}>
          {done ? 'Your account is ready. Redirecting you to sign in…' : 'Set up your profile to join the workspace.'}
        </p>
      </div>

      <Stepper steps={STEPS} current={done ? 2 : 1} />

      <div className="surface">
        {done ? (
          <div className="text-center">
            <div
              className="icon-tile mx-auto mb-3"
              style={{ width: 56, height: 56, fontSize: '1.4rem', background: 'rgba(52,211,153,.12)', color: '#34d399' }}
            >
              <i className="fa-solid fa-circle-check" />
            </div>
            <p style={{ fontSize: '.88rem', color: 'var(--tx2)' }}>
              Registration complete. You can now sign in with your new password.
            </p>
          </div>
        ) : (
          <>
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
              <div className="row g-2 mb-3">
                <div className="col-6">
                  <label className="form-label-sm">First name</label>
                  <input className="oinp" placeholder="Mariem" value={form.firstName} onChange={set('firstName')} autoFocus />
                </div>
                <div className="col-6">
                  <label className="form-label-sm">Last name</label>
                  <input className="oinp" placeholder="Ben Salah" value={form.lastName} onChange={set('lastName')} />
                </div>
              </div>

              <label className="form-label-sm">Password</label>
              <input className="oinp mb-3" type="password" placeholder="Min. 8 characters" value={form.password} onChange={set('password')} />

              <label className="form-label-sm">Confirm password</label>
              <input className="oinp mb-3" type="password" placeholder="Re-enter password" value={form.confirm} onChange={set('confirm')} />

              <button className="bgrd btn w-100 py-3 fw-semibold mt-2" disabled={loading}>
                {loading ? (
                  <>
                    <span className="spinner me-2" style={{ width: 15, height: 15, borderWidth: 2 }} />
                    Finishing up…
                  </>
                ) : (
                  <>
                    Complete Registration <i className="fa-solid fa-arrow-right ms-1 fa-sm" />
                  </>
                )}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
