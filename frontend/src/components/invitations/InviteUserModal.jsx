import { useState } from 'react';
import Modal from '@/components/common/Modal';
import { ROLES, ROLE_META } from '@/utils/constants';

/**
 * InviteUserModal — form to invite a new member (Email, Role, Message).
 *
 * Props:
 *  - open, onClose
 *  - onSend: async ({ email, role, message }) => void
 *  - sending: boolean (disables the submit button)
 */
export default function InviteUserModal({ open, onClose, onSend, sending = false }) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState(ROLES.DEVOPS_ENGINEER);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const reset = () => {
    setEmail('');
    setRole(ROLES.DEVOPS_ENGINEER);
    setMessage('');
    setError('');
  };

  const handleClose = () => {
    reset();
    onClose?.();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email.trim()) return setError('Email is required.');
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()))
      return setError('Enter a valid email address.');
    setError('');
    await onSend?.({ email: email.trim(), role, message: message.trim() });
    reset();
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Invite a member"
      icon="fa-user-plus"
      footer={
        <>
          <button className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={handleClose}>
            Cancel
          </button>
          <button
            className="bgrd btn px-3 py-2"
            style={{ fontSize: '.85rem' }}
            onClick={handleSubmit}
            disabled={sending}
          >
            {sending ? (
              <>
                <span className="spinner me-2" style={{ width: 14, height: 14, borderWidth: 2 }} />
                Sending…
              </>
            ) : (
              <>
                <i className="fa-solid fa-paper-plane me-2" />
                Send Invitation
              </>
            )}
          </button>
        </>
      }
    >
      <form onSubmit={handleSubmit}>
        {error && (
          <div
            className="mb-3 d-flex align-items-center gap-2"
            style={{
              fontSize: '.8rem',
              color: '#f87171',
              padding: '8px 12px',
              borderRadius: 10,
              background: 'rgba(248,113,113,.1)',
            }}
          >
            <i className="fa-solid fa-circle-exclamation" />
            {error}
          </div>
        )}

        <label className="form-label-sm">Email address</label>
        <input
          className="oinp mb-3"
          type="email"
          placeholder="engineer@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoFocus
        />

        <label className="form-label-sm">Role</label>
        <select className="oinp mb-3" value={role} onChange={(e) => setRole(e.target.value)}>
          {/* Only engineers can be invited — the workspace ADMIN is the
              registrant/owner, so ADMIN is intentionally not invitable. */}
          {Object.entries(ROLE_META)
            .filter(([key]) => key !== ROLES.ADMIN)
            .map(([key, meta]) => (
              <option key={key} value={key}>
                {meta.label}
              </option>
            ))}
        </select>

        <label className="form-label-sm">Message (optional)</label>
        <textarea
          className="oinp"
          rows={3}
          placeholder="Add a personal note to the invitation…"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          style={{ resize: 'vertical' }}
        />
      </form>
    </Modal>
  );
}
