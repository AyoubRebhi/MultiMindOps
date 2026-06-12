/* ============================================================================
   mockAdapter.js — helpers that make mock responses behave like real async API
   calls (network latency, not-found rejection). Keeping this in one place means
   every service module reads consistently and is trivial to delete once the
   real backend is wired up.
   ========================================================================== */

/** Resolve `data` after a short, slightly randomized delay (simulated latency). */
export function mockResponse(data, { minMs = 200, maxMs = 500 } = {}) {
  const delay = Math.round(minMs + Math.random() * (maxMs - minMs));
  return new Promise((resolve) => {
    setTimeout(() => resolve(structuredCloneSafe(data)), delay);
  });
}

/** Reject with an API-shaped error after a short delay (e.g. a missing record). */
export function mockError(message, status = 404, { ms = 300 } = {}) {
  return new Promise((_, reject) => {
    setTimeout(() => reject({ status, message }), ms);
  });
}

/** Deep clone so callers can't mutate the shared mock fixtures. */
function structuredCloneSafe(value) {
  if (typeof structuredClone === 'function') return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}
