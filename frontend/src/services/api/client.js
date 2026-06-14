/* ============================================================================
   client.js — Axios instance with real JWT auth (Phases 2 & 10).

   - Request interceptor injects `Authorization: Bearer <access>` from tokenStore.
   - Response interceptor unwraps `response.data` and normalizes errors into a
     stable `{ status, code, message }` shape the UI can branch on.
   - On a 401 from a protected call it transparently refreshes the token pair
     once (single-flight) and replays the original request. If the refresh
     fails the session is cleared and an `auth:session-expired` event is
     dispatched so AuthContext can drop to the unauthenticated state.

   Auth (login/register/me/logout) and the dashboard call the live backend
   regardless of VITE_USE_MOCK — that flag only governs the not-yet-migrated
   mock service modules.
   ========================================================================== */
import axios from 'axios';
import { tokenStore } from './tokenStore';

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

/** Legacy flag still read by the not-yet-migrated mock service modules. */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

/* ── Friendly, status-based fallbacks (Phase 10) ──────────────────────────
   Used only when the backend did not supply a usable message. We NEVER show a
   raw stack/trace — see normalizeError. */
const STATUS_MESSAGES = {
  0: 'Cannot reach the server. Check your connection and try again.',
  400: 'The request was invalid.',
  401: 'Your session is invalid or has expired. Please sign in again.',
  403: 'You do not have permission to perform this action.',
  404: 'The requested resource was not found.',
  409: 'This conflicts with existing data.',
  422: 'Some of the information provided is invalid.',
  429: 'Too many requests. Please slow down and try again.',
  500: 'Something went wrong on our end. Please try again later.',
};

/** Collapse any backend error body into `{ status, code, message }`. */
function normalizeError(error) {
  const status = error.response?.status ?? 0;
  const data = error.response?.data;
  const detail = data?.detail;
  let code = null;
  let message = null;

  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    // Canonical auth envelope: { code, message }
    code = detail.code || null;
    message = detail.message || null;
  } else if (Array.isArray(detail)) {
    // FastAPI/Pydantic 422: [{ loc, msg, type }, ...]
    message = detail.map((d) => d?.msg).filter(Boolean).join('; ') || null;
  } else if (typeof detail === 'string') {
    message = detail;
  }

  message =
    message ||
    data?.message ||
    STATUS_MESSAGES[status] ||
    error.message ||
    'Unexpected error';

  return { status, code, message };
}

function emitSessionExpired() {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('auth:session-expired'));
  }
}

const AUTH_FREE_PATHS = ['/auth/login', '/auth/register', '/auth/refresh'];
function isAuthFreePath(url = '') {
  return AUTH_FREE_PATHS.some((p) => url.includes(p));
}

/* ── Request: attach the bearer token ─────────────────────────────────────── */
apiClient.interceptors.request.use((config) => {
  const token = tokenStore.getAccess();
  if (token && !config.headers?.Authorization) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/* ── Token refresh (single-flight) ────────────────────────────────────────── */
let refreshPromise = null;

async function refreshAccessToken() {
  const refresh_token = tokenStore.getRefresh();
  if (!refresh_token) throw new Error('No refresh token available');
  // Bare axios (not apiClient) so this call does not re-enter the interceptors.
  const { data } = await axios.post(
    `${API_BASE_URL}/auth/refresh`,
    { refresh_token },
    { headers: { 'Content-Type': 'application/json' } }
  );
  tokenStore.set(data.tokens);
  return data.tokens.access_token;
}

/* ── Response: unwrap + transparent 401 refresh-and-retry ─────────────────── */
apiClient.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    const original = error.config || {};
    const status = error.response?.status;

    const canRefresh =
      status === 401 &&
      !original.__isRetryRequest &&
      !isAuthFreePath(original.url) &&
      tokenStore.getRefresh();

    if (canRefresh) {
      original.__isRetryRequest = true;
      try {
        if (!refreshPromise) {
          refreshPromise = refreshAccessToken().finally(() => {
            refreshPromise = null;
          });
        }
        const newAccess = await refreshPromise;
        original.headers = {
          ...(original.headers || {}),
          Authorization: `Bearer ${newAccess}`,
        };
        return apiClient(original);
      } catch {
        // Refresh failed → the session is genuinely dead.
        tokenStore.clear();
        emitSessionExpired();
        return Promise.reject(normalizeError(error));
      }
    }

    return Promise.reject(normalizeError(error));
  }
);

export default apiClient;
