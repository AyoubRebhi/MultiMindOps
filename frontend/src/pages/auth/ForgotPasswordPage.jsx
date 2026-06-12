import { useState } from 'react';
import { Link } from 'react-router-dom';
import { authApi } from '@/services/api/authApi';

/** ForgotPasswordPage — request a reset link (mock; no email is sent). */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email) return setError('Please enter your email.');
    setError('');
    setLoading(true);
    try {
      await authApi.forgotPassword({ email });
      setSent(true);
    } catch (err) {
      setError(err.message || 'Something went wrong.');
    } finally {
      setLoading(false);
    }
  };

  if (sent) {
    return (
      <div className="fade-in text-center">
        <div
          className="icon-tile mx-auto mb-3"
          style={{ width: 56, height: 56, fontSize: '1.4rem', background: 'rgba(52,211,153,.12)', color: '#34d399' }}
        >
          <i className="fa-regular fa-envelope-circle-check" />
        </div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: 6 }}>Check your inbox</h1>
        <p style={{ fontSize: '.88rem', color: 'var(--tx3)', marginBottom: 24 }}>
          If an account exists for <strong style={{ color: 'var(--tx2)' }}>{email}</strong>, we&apos;ve
          sent a password reset link.
        </p>
        <Link to="/auth/signin" className="boc btn w-100 py-3" style={{ fontSize: '.9rem' }}>
          <i className="fa-solid fa-arrow-left me-2" />
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <div className="fade-in">
      <h1 style={{ fontSize: '1.6rem', fontWeight: 700, marginBottom: 6 }}>Forgot password?</h1>
      <p style={{ fontSize: '.88rem', color: 'var(--tx3)', marginBottom: 28 }}>
        Enter your email and we&apos;ll send you a link to reset it.
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
        <button className="bgrd btn w-100 py-3 fw-semibold mt-2" disabled={loading}>
          {loading ? (
            <>
              <span className="spinner me-2" style={{ width: 15, height: 15, borderWidth: 2 }} />
              Sending…
            </>
          ) : (
            <>Send reset link</>
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
