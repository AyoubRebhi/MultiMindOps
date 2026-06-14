/* ============================================================================
   invitationApi.js — REAL workspace invitations (admin, Phase 8).

   Talks to the live backend (backend/app/api/routes/invitations.py). Admin
   routes are gated server-side by the ADMIN global role + scoped to the
   caller's workspace. Creating an invitation provisions the engineer's account
   and emails them their temporary credentials + acceptance link (Gmail SMTP);
   `emailStatus` reflects whether that delivery succeeded.
   ========================================================================== */
import apiClient from './client';

/** Map a backend admin-view invitation into the UI shape (camelCase). */
function mapInvitation(api) {
  if (!api) return null;
  return {
    id: api.id,
    email: api.email,
    role: api.role,
    status: api.status,
    invitedBy: api.invited_by || '—',
    message: api.message || '',
    token: api.token,
    // Email delivery (Phase 8): PENDING | SENT | FAILED | SKIPPED.
    emailStatus: api.email_status || 'PENDING',
    emailError: api.email_error || null,
    emailSentAt: api.email_sent_at || null,
    sentAt: api.sent_at,
    expiresAt: api.expires_at,
    acceptedAt: api.accepted_at || null,
  };
}

export const invitationApi = {
  /** GET /invitations — all invitations in the admin's workspace. */
  async list() {
    const data = await apiClient.get('/invitations');
    return (Array.isArray(data) ? data : []).map(mapInvitation);
  },

  /** POST /invitations — create (or refresh) a pending invitation. */
  async create({ email, role, message } = {}) {
    const data = await apiClient.post('/invitations', { email, role, message });
    return mapInvitation(data);
  },

  /** POST /invitations/:id/resend — refresh the expiry window. */
  async resend(id) {
    const data = await apiClient.post(`/invitations/${encodeURIComponent(id)}/resend`);
    return mapInvitation(data);
  },

  /** DELETE /invitations/:id — revoke a pending invitation. */
  async revoke(id) {
    const data = await apiClient.delete(`/invitations/${encodeURIComponent(id)}`);
    return mapInvitation(data);
  },
};

export default invitationApi;
