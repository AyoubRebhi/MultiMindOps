import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { ROLES } from '@/utils/constants';

/** SignInPage — email/password sign-in (mock). */
export default function SignInPage() {
  const { signIn, switchRole } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email || !password) return setError('Please enter your email and password.');
    setError('');
    setLoading(true);
    try {
      await signIn({ email, password });
      navigate('/');
    } finally {
      setLoading(false);
    }
  };

  const demoAs = (role) => {
    switchRole(role);
    navigate('/');
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

      {/* Demo-only quick access (no backend) */}
      <div className="d-flex align-items-center gap-2 my-3" style={{ color: 'var(--tx3)' }}>
        <span style={{ flex: 1, height: 1, background: 'var(--bd)' }} />
        <span style={{ fontSize: '.7rem' }}>QUICK DEMO ACCESS</span>
        <span style={{ flex: 1, height: 1, background: 'var(--bd)' }} />
      </div>
      <div className="d-flex gap-2">
        <button className="boc btn flex-fill py-2" style={{ fontSize: '.8rem' }} onClick={() => demoAs(ROLES.ADMIN)}>
          <i className="fa-solid fa-crown me-2" style={{ color: '#a78bfa' }} />
          Enter as Admin
        </button>
        <button className="boc btn flex-fill py-2" style={{ fontSize: '.8rem' }} onClick={() => demoAs(ROLES.DEVOPS_ENGINEER)}>
          <i className="fa-solid fa-user-gear me-2" style={{ color: '#60a5fa' }} />
          Enter as Engineer
        </button>
      </div>
    </div>
  );
}
