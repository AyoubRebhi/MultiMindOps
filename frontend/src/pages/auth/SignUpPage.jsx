import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';

/**
 * SignUpPage — Admin account creation against the real backend (Phase 4).
 * A successful register auto-provisions the workspace and signs the admin in;
 * we then land on the dashboard (which renders the admin view for their role).
 */
export default function SignUpPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    firstName: '',
    lastName: '',
    email: '',
    password: '',
    confirm: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  // Mirror the backend password policy (>=8 chars, upper + lower + digit) so the
  // user gets immediate feedback instead of a round-trip 422.
  const validatePassword = (pw) => {
    if (pw.length < 8) return 'Password must be at least 8 characters.';
    if (!/[a-z]/.test(pw) || !/[A-Z]/.test(pw) || !/[0-9]/.test(pw))
      return 'Password must include an uppercase letter, a lowercase letter, and a digit.';
    return '';
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const { firstName, lastName, email, password, confirm } = form;
    if (!firstName || !lastName || !email || !password)
      return setError('Please fill in all fields.');
    const pwError = validatePassword(password);
    if (pwError) return setError(pwError);
    if (password !== confirm) return setError('Passwords do not match.');
    setError('');
    setLoading(true);
    try {
      await register({
        email,
        password,
        displayName: `${firstName} ${lastName}`.trim(),
      });
      navigate('/', { replace: true });
    } catch (err) {
      setError(err?.message || 'Could not create your account. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fade-in">
      <h1 style={{ fontSize: '1.6rem', fontWeight: 700, marginBottom: 6 }}>Create your account</h1>
      <p style={{ fontSize: '.88rem', color: 'var(--tx3)', marginBottom: 28 }}>
        Start your workspace as an Admin — no credit card required.
      </p>

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
            <input className="oinp" placeholder="Ayoub" value={form.firstName} onChange={set('firstName')} />
          </div>
          <div className="col-6">
            <label className="form-label-sm">Last name</label>
            <input className="oinp" placeholder="Rebhi" value={form.lastName} onChange={set('lastName')} />
          </div>
        </div>

        <label className="form-label-sm">Work email</label>
        <input className="oinp mb-3" type="email" placeholder="you@company.com" value={form.email} onChange={set('email')} autoComplete="email" />

        <label className="form-label-sm">Password</label>
        <input className="oinp mb-3" type="password" placeholder="Min. 8 chars, with a capital & a number" value={form.password} onChange={set('password')} autoComplete="new-password" />

        <label className="form-label-sm">Confirm password</label>
        <input className="oinp mb-3" type="password" placeholder="Re-enter password" value={form.confirm} onChange={set('confirm')} autoComplete="new-password" />

        <button className="bgrd btn w-100 py-3 fw-semibold mt-2" disabled={loading}>
          {loading ? (
            <>
              <span className="spinner me-2" style={{ width: 15, height: 15, borderWidth: 2 }} />
              Creating account…
            </>
          ) : (
            <>
              Create Account <i className="fa-solid fa-arrow-right ms-1 fa-sm" />
            </>
          )}
        </button>
      </form>

      <p className="text-center mt-4" style={{ fontSize: '.85rem', color: 'var(--tx3)' }}>
        Already have an account?{' '}
        <Link to="/auth/signin" className="card-link">
          Sign in
        </Link>
      </p>
    </div>
  );
}
