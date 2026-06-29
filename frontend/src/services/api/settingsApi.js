/* ============================================================================
   settingsApi.js — REAL backend integration for user self-service settings.

   Talks to the live FastAPI settings router (backend/app/api/routes/settings.py).
   Identity-only: profile (display name / email) + password change. The global
   `role` is NEVER sent — it is read-only from the user's perspective (changed
   only via admin member management).

   Backend contract:
     GET /api/settings/profile                              -> UserPublic
     PUT /api/settings/profile {display_name?, email?, current_password?} -> UserPublic
     PUT /api/settings/password {current_password, new_password}          -> UserPublic
   ========================================================================== */
import apiClient from './client';
import { normalizeUser } from './authApi';

export const settingsApi = {
  /** GET /api/settings/profile */
  async getProfile() {
    const data = await apiClient.get('/settings/profile');
    return normalizeUser(data);
  },

  /** PUT /api/settings/profile — partial update of display name / email.
   *  `currentPassword` is required by the backend ONLY when the email changes. */
  async updateProfile({ displayName, email, currentPassword } = {}) {
    const body = {};
    if (displayName !== undefined) body.display_name = displayName;
    if (email !== undefined) body.email = email;
    if (currentPassword) body.current_password = currentPassword;
    const data = await apiClient.put('/settings/profile', body);
    return normalizeUser(data);
  },

  /** PUT /api/settings/password — change own password. */
  async changePassword({ currentPassword, newPassword } = {}) {
    const data = await apiClient.put('/settings/password', {
      current_password: currentPassword,
      new_password: newPassword,
    });
    return normalizeUser(data);
  },
};

export default settingsApi;
