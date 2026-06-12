/* ============================================================================
   invitationApi.js — workspace invitations. MOCK ONLY (no email sending).
   ========================================================================== */
import { mockInvitations } from '@/services/mock/mockInvitations';
import { mockResponse, mockError } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

export const invitationApi = {
  /** GET /invitations */
  async list() {
    // if (!USE_MOCK) return apiClient.get('/invitations');
    return mockResponse(mockInvitations);
  },

  /** GET /invitations/:token */
  async getByToken(token) {
    // if (!USE_MOCK) return apiClient.get(`/invitations/${token}`);
    const inv = mockInvitations.find((i) => i.token === token);
    return inv ? mockResponse(inv) : mockError('Invitation not found');
  },

  /** POST /invitations — send a new invitation. */
  async create(payload) {
    // if (!USE_MOCK) return apiClient.post('/invitations', payload);
    const now = Date.now();
    return mockResponse({
      id: `inv-${now}`,
      status: 'pending',
      invitedBy: 'Ayoub Rebhi',
      token: `tok_${Math.random().toString(36).slice(2, 8)}`,
      sentAt: new Date(now).toISOString(),
      expiresAt: new Date(now + WEEK_MS).toISOString(),
      ...payload,
    });
  },

  /** POST /invitations/:id/resend */
  async resend(id) {
    // if (!USE_MOCK) return apiClient.post(`/invitations/${id}/resend`);
    const now = Date.now();
    return mockResponse({
      id,
      status: 'pending',
      sentAt: new Date(now).toISOString(),
      expiresAt: new Date(now + WEEK_MS).toISOString(),
    });
  },

  /** DELETE /invitations/:id — revoke a pending invitation. */
  async revoke(id) {
    // if (!USE_MOCK) return apiClient.delete(`/invitations/${id}`);
    return mockResponse({ id, status: 'revoked' });
  },
};

export default invitationApi;
