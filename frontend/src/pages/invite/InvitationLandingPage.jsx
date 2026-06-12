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
 * Shows the workspace, who invited them, the role and status, then leads into
 * completing registration.
 */
export default function InvitationLandingPage() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { data: invite, loading } = useAsync(() => authApi.getInvitation(token), [token]);

  if (loading || !invite) {
    return <LoadingSpinner center label="Loading invitation…" />;
  }

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
        <p style={{ fontSize: '.86rem', color: 'var(--tx3)', marginBottom: 22 }}>
          {invite.company}
        </p>

        <div className="d-flex flex-column gap-2 text-start mb-4">
          <InfoRow label="Workspace" value={invite.workspaceName} icon="fa-building" />
          <InfoRow label="Invited by" value={`${invite.invitedBy} · ${invite.invitedByEmail}`} icon="fa-user" />
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

        <button
          className="bgrd btn w-100 py-3 fw-semibold"
          onClick={() => navigate(`/invite/${token}/complete`)}
        >
          Accept Invitation <i className="fa-solid fa-arrow-right ms-1 fa-sm" />
        </button>
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
