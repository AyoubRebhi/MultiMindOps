import { useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';

/** SignInPage — email/password sign-in against the real backend (Phase 5). */
export default function SignInPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Where to go after a successful sign-in: the page they were bounced from,
  // else the dashboard (which renders the right view for their role).
  const redirectTo = location.state?.from?.pathname || '/';

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email || !password) return setError('Please enter your email and password.');
    setError('');
    setLoading(true);
    try {
      const user = await login({ email, password });
      // Invited engineers sign in with a temporary password and must change it
      // before anything else (Phase 7).
      if (user?.mustChangePassword) {
        navigate('/change-password', { replace: true });
      } else {
        navigate(redirectTo, { replace: true });
      }
    } catch (err) {
      // Friendly, status-normalized message from the Axios client.
      setError(err?.message || 'Sign in failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fade-in">
      <h1 style={{ fontSize: '1.6rem', fontWeight: 700, marginBottom: 6 }}>Welcome back</h1>
      <p style={{ fontSize: '.88rem', color: 'var(--tx3)', marginBottom: 28 }}>
        Sign in to your MultiMinds AI workspace.
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
        <label className="form-label-sm">Email</label>
        <input
          className="oinp mb-3"
          type="email"
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
        />

        <div className="d-flex align-items-center justify-content-between">
          <label className="form-label-sm">Password</label>
          <Link to="/auth/forgot-password" className="card-link" style={{ fontSize: '.76rem' }}>
            Forgot password?
          </Link>
        </div>
        <input
          className="oinp mb-3"
          type="password"
          placeholder="••••••••"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />

        <button className="bgrd btn w-100 py-3 fw-semibold mt-2" disabled={loading}>
          {loading ? (
            <>
              <span className="spinner me-2" style={{ width: 15, height: 15, borderWidth: 2 }} />
              Signing in…
            </>
          ) : (
            <>
              Sign In <i className="fa-solid fa-arrow-right ms-1 fa-sm" />
            </>
          )}
        </button>
      </form>

      <p className="text-center mt-4" style={{ fontSize: '.85rem', color: 'var(--tx3)' }}>
        Don&apos;t have an account?{' '}
        <Link to="/auth/signup" className="card-link">
          Create one
        </Link>
      </p>
    </div>
  );
}
