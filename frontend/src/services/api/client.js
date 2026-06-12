/* ============================================================================
   client.js — Axios instance, PREPARED ONLY.

   In this foundation phase the service modules return mock data and DO NOT call
   real endpoints. This client exists so that wiring the real backend later is a
   one-line change inside each service module (swap the mock call for `apiClient`).

   Switching on the backend:
     1. Set VITE_USE_MOCK=false in .env
     2. In each service module, replace the mock branch with the apiClient call.
   ========================================================================== */
import axios from 'axios';

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

/** When true (default for this phase) the service layer serves mock data. */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

// Request interceptor — attach auth token later (auth is intentionally out of
// scope for this phase).
apiClient.interceptors.request.use((config) => {
  // const token = getToken();
  // if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Response interceptor — unwrap data and normalize errors for the UI.
apiClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const normalized = {
      status: error.response?.status ?? 0,
      message:
        error.response?.data?.detail ||
        error.response?.data?.message ||
        error.message ||
        'Unexpected network error',
    };
    return Promise.reject(normalized);
  }
);

export default apiClient;
