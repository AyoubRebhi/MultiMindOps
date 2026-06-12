/* ============================================================================
   awsCredentialsApi.js — workspace AWS credentials. MOCK ONLY.
   No secret is ever persisted or returned in plaintext (only last-4 tails).
   ========================================================================== */
import { mockAwsCredentials } from '@/services/mock/mockAwsCredentials';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const awsCredentialsApi = {
  /** GET /workspace/aws-credentials */
  async get() {
    // if (!USE_MOCK) return apiClient.get('/workspace/aws-credentials');
    return mockResponse(mockAwsCredentials);
  },

  /** PUT /workspace/aws-credentials — save new credentials. */
  async save(payload) {
    // if (!USE_MOCK) return apiClient.put('/workspace/aws-credentials', payload);
    // Only retain non-secret metadata + last-4 tails in the mock response.
    const last4 = (v) => (v ? String(v).slice(-4) : null);
    return mockResponse({
      ...mockAwsCredentials,
      region: payload.region ?? mockAwsCredentials.region,
      accessKeyIdLast4: last4(payload.accessKeyId) ?? mockAwsCredentials.accessKeyIdLast4,
      secretAccessKeyLast4:
        last4(payload.secretAccessKey) ?? mockAwsCredentials.secretAccessKeyLast4,
      sessionTokenLast4: last4(payload.sessionToken),
      hasSessionToken: Boolean(payload.sessionToken),
      status: 'connected',
      lastUpdated: new Date().toISOString(),
    });
  },

  /** POST /workspace/aws-credentials/test — validate the connection. */
  async testConnection() {
    // if (!USE_MOCK) return apiClient.post('/workspace/aws-credentials/test');
    return mockResponse(
      {
        status: 'connected',
        accountId: mockAwsCredentials.accountId,
        testedAt: new Date().toISOString(),
        message: 'Successfully authenticated with AWS STS (mock).',
      },
      { minMs: 700, maxMs: 1200 }
    );
  },
};

export default awsCredentialsApi;
