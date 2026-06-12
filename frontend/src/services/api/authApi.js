/* ============================================================================
   authApi.js — authentication & registration. MOCK ONLY.
   No JWT, no real credentials check, no email sending. Every call resolves with
   a believable shape so the UI flow can be exercised end-to-end.
   ========================================================================== */
import { mockCurrentUser, mockEngineerUser } from '@/services/mock/mockCurrentUser';
import { mockPendingInvitation } from '@/services/mock/mockInvitations';
import { mockResponse, mockError } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const authApi = {
  /** POST /auth/sign-in — returns the mock user (admin by default). */
  async signIn({ email } = {}) {
    // if (!USE_MOCK) return apiClient.post('/auth/sign-in', { email, password });
    const user =
      email && email.toLowerCase() === mockEngineerUser.email
        ? mockEngineerUser
        : mockCurrentUser;
    return mockResponse({ user, token: 'mock.jwt.token' });
  },

  /** POST /auth/sign-up — admin account creation (pre-workspace). */
  async signUp(payload) {
    // if (!USE_MOCK) return apiClient.post('/auth/sign-up', payload);
    return mockResponse({
      user: {
        ...mockCurrentUser,
        ...payload,
        name: `${payload.firstName || ''} ${payload.lastName || ''}`.trim(),
        role: 'ADMIN',
        workspaceId: null,
      },
      token: 'mock.jwt.token',
    });
  },

  /** POST /auth/forgot-password — pretends to send a reset email. */
  async forgotPassword({ email }) {
    // if (!USE_MOCK) return apiClient.post('/auth/forgot-password', { email });
    if (!email) return mockError('Email is required', 400);
    return mockResponse({ sent: true, email });
  },

  /** POST /auth/reset-password */
  async resetPassword(payload) {
    // if (!USE_MOCK) return apiClient.post('/auth/reset-password', payload);
    return mockResponse({ success: true, token: payload?.token ?? null });
  },

  /** GET /invitations/:token — public lookup for the invitation landing page. */
  async getInvitation(token) {
    // if (!USE_MOCK) return apiClient.get(`/invitations/${token}`);
    return mockResponse({ ...mockPendingInvitation, token });
  },

  /** POST /invitations/:token/accept — engineer completes registration. */
  async completeRegistration(token, payload) {
    // if (!USE_MOCK) return apiClient.post(`/invitations/${token}/accept`, payload);
    return mockResponse({
      user: {
        ...mockEngineerUser,
        ...payload,
        name: `${payload.firstName || ''} ${payload.lastName || ''}`.trim(),
        role: 'DEVOPS_ENGINEER',
      },
    });
  },

  /** POST /auth/sign-out */
  async signOut() {
    // if (!USE_MOCK) return apiClient.post('/auth/sign-out');
    return mockResponse({ success: true }, { minMs: 80, maxMs: 160 });
  },
};

export default authApi;
