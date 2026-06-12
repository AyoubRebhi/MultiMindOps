/* ============================================================================
   mockAwsCredentials.js — workspace AWS credentials.

   SECURITY NOTE: secrets are never stored or shown in plaintext. We keep only
   the last 4 characters; the UI masks everything else. The "show" toggle
   reveals the last-4 form only — never a full secret.
   ========================================================================== */

export const mockAwsCredentials = {
  region: 'eu-west-1',
  accountId: '123456789012',
  // Access Key IDs are not secret, but we still present them masked for consistency.
  accessKeyIdLast4: 'WXYZ',
  secretAccessKeyLast4: 'aB12',
  sessionTokenLast4: 'Kf90',
  hasSessionToken: true,
  status: 'connected',
  lastUpdated: '2026-06-11T14:05:00Z',
  lastTestedAt: '2026-06-11T14:06:00Z',
  updatedBy: 'Ayoub Rebhi',
};
