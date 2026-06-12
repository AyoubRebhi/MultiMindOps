import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { authApi } from '@/services/api/authApi';

/** ResetPasswordPage — set a new password from a reset link (mock). */
export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!password) return setError('Please enter a new password.');
    if (password.length < 8) return setError('Password must be at least 8 characters.');
    if (password !== confirm) return setError('Passwords do not match.');
    setError('');
    setLoading(true);
    try {
      await authApi.resetPassword({ password });
      setDone(true);
      setTimeout(() => navigate('/auth/signin'), 1600);
    } finally {
      setLoading(false);
    }
  };

  if (done) {
    return (
      <div className="fade-in text-center">
        <div
          className="icon-tile mx-auto mb-3"
          style={{ width: 56, height: 56, fontSize: '1.4rem', background: 'rgba(52,211,153,.12)', color: '#34d399' }}
        >
          <i className="fa-solid fa-circle-check" />
        </div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: 6 }}>Password updated</h1>
        <p style={{ fontSize: '.88rem', color: 'var(--tx3)' }}>
          Redirecting you to sign in…
        </p>
      </div>
    );
  }

  return (
    <div className="fade-in">
      <h1 style={{ fontSize: '1.6rem', fontWeight: 700, marginBottom: 6 }}>Set a new password</h1>
      <p style={{ fontSize: '.88rem', color: 'var(--tx3)', marginBottom: 28 }}>
        Choose a strong password you don&apos;t use elsewhere.
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
        <label className="form-label-sm">New password</label>
        <input className="oinp mb-3" type="password" placeholder="Min. 8 characters" value={password} onChange={(e) => setPassword(e.target.value)} />

        <label className="form-label-sm">Confirm new password</label>
        <input className="oinp mb-3" type="password" placeholder="Re-enter password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />

        <button className="bgrd btn w-100 py-3 fw-semibold mt-2" disabled={loading}>
          {loading ? (
            <>
              <span className="spinner me-2" style={{ width: 15, height: 15, borderWidth: 2 }} />
              Updating…
            </>
          ) : (
            <>Reset password</>
          )}
        </button>
      </form>

      <p className="text-center mt-4" style={{ fontSize: '.85rem', color: 'var(--tx3)' }}>
        <Link to="/auth/signin" className="card-link">
          <i className="fa-solid fa-arrow-left me-1" />
          Back to sign in
        </Link>
      </p>
    </div>
  );
}
