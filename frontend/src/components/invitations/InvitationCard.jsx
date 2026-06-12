import RoleBadge from '@/components/common/RoleBadge';
import StatusBadge from '@/components/common/StatusBadge';
import { formatDate, timeAgo } from '@/utils/formatters';

/**
 * InvitationCard — a single invitation with its lifecycle state and dates.
 *
 * Props:
 *  - invitation: see mockInvitations shape
 *  - onResend, onRevoke: optional action callbacks (shown for pending only)
 */
export default function InvitationCard({ invitation, onResend, onRevoke }) {
  if (!invitation) return null;
  const { email, role, status, invitedBy, message, sentAt, expiresAt } = invitation;
  const isPending = status === 'pending';
  const isExpired = status === 'expired';

  return (
    <div className="surface h-100 d-flex flex-column">
      <div className="d-flex align-items-start justify-content-between mb-2">
        <div className="d-flex align-items-center gap-2" style={{ minWidth: 0 }}>
          <div
            className="icon-tile"
            style={{ background: 'var(--bg3)', color: 'var(--tx2)' }}
          >
            <i className="fa-regular fa-envelope" />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {email}
            </div>
            <div style={{ fontSize: '.72rem', color: 'var(--tx3)' }}>
              Invited by {invitedBy}
            </div>
          </div>
        </div>
        <StatusBadge status={status} />
      </div>

      {message && (
        <p
          style={{
            fontSize: '.8rem',
            color: 'var(--tx2)',
            margin: '4px 0 12px',
            fontStyle: 'italic',
          }}
        >
          “{message}”
        </p>
      )}

      <div className="d-flex flex-wrap gap-2 mb-3">
        <RoleBadge role={role} />
      </div>

      <div
        className="d-flex align-items-center justify-content-between mt-auto pt-3"
        style={{ borderTop: '1px solid var(--bd)', fontSize: '.74rem', color: 'var(--tx3)' }}
      >
        <span>
          <i className="fa-regular fa-paper-plane me-1" />
          Sent {timeAgo(sentAt)}
        </span>
        <span style={{ color: isExpired ? '#f87171' : 'var(--tx3)' }}>
          <i className="fa-regular fa-hourglass me-1" />
          {isExpired ? 'Expired' : 'Expires'} {formatDate(expiresAt)}
        </span>
      </div>

      {(isPending || isExpired) && (onResend || onRevoke) && (
        <div className="d-flex gap-2 mt-3">
          {onResend && (
            <button
              className="boc btn flex-fill py-2"
              style={{ fontSize: '.78rem', borderRadius: 10 }}
              onClick={() => onResend(invitation)}
            >
              <i className="fa-solid fa-rotate-right me-1" />
              {isExpired ? 'Re-invite' : 'Resend'}
            </button>
          )}
          {onRevoke && isPending && (
            <button
              className="boc btn flex-fill py-2"
              style={{ fontSize: '.78rem', borderRadius: 10, color: '#f87171' }}
              onClick={() => onRevoke(invitation)}
            >
              <i className="fa-solid fa-ban me-1" />
              Revoke
            </button>
          )}
        </div>
      )}
    </div>
  );
}
