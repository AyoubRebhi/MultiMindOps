/* ============================================================================
   tokenStore.js — JWT persistence (Phase 2).

   Single source of truth for the access + refresh token pair. Stored in
   localStorage so a page refresh keeps the session; never hardcoded, never
   logged. The Axios client (client.js) reads the access token here to inject
   the Authorization header, and rotates the pair through here on refresh.

   Shape persisted under one key:
     { access_token, refresh_token, token_type, expires_in, stored_at }
   ========================================================================== */

const TOKENS_KEY = 'cloudforge.auth.tokens';

function read() {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(TOKENS_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export const tokenStore = {
  /** Persist a fresh token pair (from login / register / refresh / accept). */
  set(tokens) {
    if (typeof window === 'undefined' || !tokens?.access_token) return;
    const payload = {
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token || null,
      token_type: tokens.token_type || 'bearer',
      expires_in: tokens.expires_in ?? null,
      stored_at: Date.now(),
    };
    try {
      window.localStorage.setItem(TOKENS_KEY, JSON.stringify(payload));
    } catch {
      /* storage full / disabled — ignore, the request will 401 and recover */
    }
  },

  getAccess() {
    return read()?.access_token || null;
  },

  getRefresh() {
    return read()?.refresh_token || null;
  },

  /** True when an access token is present (cheap "maybe authenticated" check). */
  has() {
    return !!this.getAccess();
  },

  clear() {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.removeItem(TOKENS_KEY);
    } catch {
      /* ignore */
    }
  },
};

export default tokenStore;
