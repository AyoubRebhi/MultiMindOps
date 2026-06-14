/* ============================================================================
   authApi.js — REAL backend authentication + invitation acceptance (Phase 1).

   Talks to the live FastAPI auth surface (see backend/app/api/routes/auth.py
   and invitations.py). The Axios client injects the JWT and handles refresh,
   so this module only shapes requests and maps the backend payloads into the
   frontend's user/invitation shapes.

   Backend contract:
     POST /auth/register {email,password,display_name} -> { user, tokens }
     POST /auth/login    {email,password}              -> { user, tokens }
     POST /auth/logout   {refresh_token?}              -> { revoked_sessions }
     GET  /auth/me                                     -> UserPublic
     GET  /invitations/:token                          -> InvitationLanding
     POST /invitations/:token/accept {password,...}    -> { user, tokens }
   ========================================================================== */
import apiClient from './client';

/* ── Mappers ─────────────────────────────────────────────────────────────── */

/** Map a backend UserPublic into the shape the UI (navbar/sidebar/badges) uses. */
export function normalizeUser(apiUser) {
  if (!apiUser) return null;
  const workspace = apiUser.workspace || null;
  return {
    id: apiUser.id,
    email: apiUser.email,
    name: apiUser.display_name || apiUser.email,
    displayName: apiUser.display_name || null,
    role: apiUser.role || 'DEVOPS_ENGINEER',
    avatarUrl: apiUser.avatar_url || null,
    accountStatus: apiUser.account_status || 'active',
    emailVerified: apiUser.email_verified === 'true' || apiUser.email_verified === true,
    // Invited engineers get a temp password and must set their own before
    // normal access — drives the forced password-change redirect.
    mustChangePassword:
      apiUser.must_change_password === 'true' || apiUser.must_change_password === true,
    workspaceId: apiUser.workspace_id || workspace?.id || null,
    workspaceName: workspace?.name || null,
    workspace: workspace ? { id: workspace.id, name: workspace.name, plan: workspace.plan } : null,
  };
}

/** Map the public invitation landing payload into the UI shape. */
export function normalizeInvitation(api) {
  if (!api) return null;
  return {
    token: api.token,
    email: api.email,
    role: api.role,
    status: api.status,
    workspaceName: api.workspace_name,
    company: api.workspace_name, // no separate company entity in this build
    invitedBy: api.invited_by || api.invited_by_email || 'A workspace admin',
    invitedByEmail: api.invited_by_email || '',
    message: api.message || '',
    expiresAt: api.expires_at,
  };
}

/* ── API ─────────────────────────────────────────────────────────────────── */

export const authApi = {
  /** POST /auth/login — returns { user, tokens }. */
  async signIn({ email, password } = {}) {
    return apiClient.post('/auth/login', { email, password });
  },

  /** POST /auth/register — admin account creation (auto-provisions workspace). */
  async signUp({ email, password, displayName, display_name } = {}) {
    return apiClient.post('/auth/register', {
      email,
      password,
      display_name: display_name ?? displayName ?? null,
    });
  },

  /** GET /auth/me — the authenticated user (UserPublic). */
  async getCurrentUser() {
    return apiClient.get('/auth/me');
  },

  /** POST /auth/change-password — change the caller's password (also clears a
   *  forced-change requirement). Returns the refreshed UserPublic. */
  async changePassword({ currentPassword, newPassword, current_password, new_password } = {}) {
    return apiClient.post('/auth/change-password', {
      current_password: current_password ?? currentPassword,
      new_password: new_password ?? newPassword,
    });
  },

  /** POST /auth/logout — best-effort session revoke. */
  async signOut({ refresh_token } = {}) {
    return apiClient.post('/auth/logout', refresh_token ? { refresh_token } : {});
  },

  /** GET /invitations/:token — public landing-page lookup. */
  async getInvitation(token) {
    const data = await apiClient.get(`/invitations/${encodeURIComponent(token)}`);
    return normalizeInvitation(data);
  },

  /** POST /invitations/:token/accept — invitee sets a password + name. */
  async acceptInvitation(token, { password, displayName, display_name } = {}) {
    return apiClient.post(`/invitations/${encodeURIComponent(token)}/accept`, {
      password,
      display_name: display_name ?? displayName ?? null,
    });
  },

  /* Backward-compatible alias used by CompleteRegistrationPage. */
  async completeRegistration(token, payload) {
    return this.acceptInvitation(token, payload);
  },

  /* ── Not backend-backed yet (no reset endpoints). Kept as graceful no-ops so
     the existing password-reset pages do not crash; they surface a neutral
     "if an account exists…" style response. ───────────────────────────────── */
  async forgotPassword({ email } = {}) {
    return Promise.resolve({ sent: true, email });
  },
  async resetPassword(payload = {}) {
    return Promise.resolve({ success: true, token: payload?.token ?? null });
  },
};

export default authApi;
