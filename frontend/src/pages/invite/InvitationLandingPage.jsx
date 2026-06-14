import { useParams, useNavigate } from 'react-router-dom';
import Avatar from '@/components/common/Avatar';
import RoleBadge from '@/components/common/RoleBadge';
import StatusBadge from '@/components/common/StatusBadge';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { useAsync } from '@/hooks/useAsync';
import { authApi } from '@/services/api/authApi';
import { formatDate } from '@/utils/formatters';

/**
 * InvitationLandingPage — what an invited engineer sees from their email link.
 * Resolves the invitation by token from the real backend, shows the workspace,
 * who invited them, role and status, then leads into completing registration.
 * Only a *pending* invitation can be accepted — expired / accepted / revoked
 * states are surfaced read-only.
 */
export default function InvitationLandingPage() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { data: invite, loading, error } = useAsync(() => authApi.getInvitation(token), [token]);

  if (loading) {
    return <LoadingSpinner center label="Loading invitation…" />;
  }

  // Not found / network error — never expose the raw backend message verbatim.
  if (error || !invite) {
    return (
      <div className="fade-in">
        <div className="surface text-center">
          <div
            className="icon-tile mx-auto mb-3"
            style={{ width: 56, height: 56, fontSize: '1.4rem', background: 'rgba(248,113,113,.12)', color: '#f87171' }}
          >
            <i className="fa-solid fa-link-slash" />
          </div>
          <h1 style={{ fontSize: '1.4rem', fontWeight: 700, marginBottom: 6 }}>Invitation not found</h1>
          <p style={{ fontSize: '.86rem', color: 'var(--tx3)', marginBottom: 20 }}>
            This invitation link is invalid or no longer exists. Ask your workspace admin to send a new one.
          </p>
          <button className="boc btn px-4 py-2" onClick={() => navigate('/auth/signin')}>
            Go to Sign In
          </button>
        </div>
      </div>
    );
  }

  const isPending = invite.status === 'pending';

  return (
    <div className="fade-in">
      <div className="surface text-center">
        <div className="d-flex align-items-center justify-content-center gap-2 mb-3">
          <Avatar name={invite.workspaceName} size={52} />
        </div>
        <span className="slbl justify-content-center" style={{ display: 'inline-flex' }}>
          You&apos;re invited
        </span>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: 4 }}>
          Join {invite.workspaceName}
        </h1>
        <p style={{ fontSize: '.86rem', color: 'var(--tx3)', marginBottom: 22 }}>{invite.email}</p>

        <div className="d-flex flex-column gap-2 text-start mb-4">
          <InfoRow label="Workspace" value={invite.workspaceName} icon="fa-building" />
          <InfoRow
            label="Invited by"
            value={invite.invitedByEmail ? `${invite.invitedBy} · ${invite.invitedByEmail}` : invite.invitedBy}
            icon="fa-user"
          />
          <InfoRow label="Your role" icon="fa-id-badge">
            <RoleBadge role={invite.role} />
          </InfoRow>
          <InfoRow label="Status" icon="fa-circle-info">
            <StatusBadge status={invite.status} />
          </InfoRow>
          <InfoRow label="Expires" value={formatDate(invite.expiresAt)} icon="fa-hourglass-half" />
        </div>

        {invite.message && (
          <p
            style={{
              fontSize: '.84rem',
              color: 'var(--tx2)',
              fontStyle: 'italic',
              background: 'var(--bg3)',
              borderRadius: 12,
              padding: '12px 14px',
              marginBottom: 20,
            }}
          >
            “{invite.message}”
          </p>
        )}

        {isPending ? (
          <button
            className="bgrd btn w-100 py-3 fw-semibold"
            onClick={() => navigate(`/invite/${token}/complete`)}
          >
            Accept Invitation <i className="fa-solid fa-arrow-right ms-1 fa-sm" />
          </button>
        ) : (
          <div
            style={{
              fontSize: '.84rem',
              color: 'var(--tx3)',
              padding: '12px 14px',
              background: 'var(--bg3)',
              borderRadius: 12,
            }}
          >
            This invitation is {invite.status} and can no longer be accepted.{' '}
            <button className="card-link" style={{ background: 'none', border: 'none', padding: 0 }} onClick={() => navigate('/auth/signin')}>
              Sign in
            </button>{' '}
            if you already have an account.
          </div>
        )}
      </div>
    </div>
  );
}

function InfoRow({ label, value, icon, children }) {
  return (
    <div
      className="d-flex align-items-center justify-content-between"
      style={{ padding: '10px 14px', background: 'var(--bg3)', borderRadius: 12 }}
    >
      <span style={{ fontSize: '.8rem', color: 'var(--tx3)' }}>
        <i className={`fa-solid ${icon} me-2`} />
        {label}
      </span>
      {children || <span style={{ fontSize: '.84rem', fontWeight: 600 }}>{value}</span>}
    </div>
  );
}
