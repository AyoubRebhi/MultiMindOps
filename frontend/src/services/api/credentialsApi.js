/* ============================================================================
   credentialsApi.js — REAL backend integration for PROJECT-scoped settings
   and DevOps credentials (GitHub PAT + AWS keys).

   Credentials belong to a Project (never global) — every call is scoped by
   projectId. Secrets are WRITE-ONLY: the backend returns only `configured`
   flags + non-secret metadata (region / account / last-4). No endpoint ever
   returns a token or AWS secret.

   Backend contract:
     GET    /api/projects/:id/settings                       -> ProjectSettingsResponse
     PUT    /api/projects/:id/settings {repository_url?, default_branch?, repository_visibility?}
     POST   /api/projects/:id/credentials/github {token, label?} -> CredentialResponse (masked)
     POST   /api/projects/:id/credentials/aws {access_key_id, secret_access_key, region, account_name?}
                                                              -> AwsCredentialStatus (masked)
     DELETE /api/projects/:id/credentials/:provider          -> {deleted, provider}
   ========================================================================== */
import apiClient from './client';

const enc = encodeURIComponent;

/** Map the backend ProjectSettingsResponse into the UI shape. */
export function mapProjectSettings(api) {
  if (!api) return null;
  const creds = api.credentials || {};
  const aws = creds.aws || {};
  return {
    repositoryUrl: api.repository_url || '',
    repositoryVisibility: api.repository_visibility || 'public',
    defaultBranch: api.default_branch || '',
    github: { configured: Boolean(creds.github?.configured) },
    aws: {
      configured: Boolean(aws.configured),
      region: aws.region || null,
      accountName: aws.account_name || null,
      accessKeyIdLast4: aws.access_key_id_last4 || null,
    },
  };
}

export const credentialsApi = {
  /** GET /api/projects/:id/settings */
  async getProjectSettings(projectId) {
    const data = await apiClient.get(`/projects/${enc(projectId)}/settings`);
    return mapProjectSettings(data);
  },

  /** PUT /api/projects/:id/settings — repository URL / branch / visibility. */
  async updateProjectSettings(projectId, { repositoryUrl, defaultBranch, repositoryVisibility } = {}) {
    const body = {};
    if (repositoryUrl !== undefined) body.repository_url = repositoryUrl;
    if (defaultBranch !== undefined) body.default_branch = defaultBranch;
    if (repositoryVisibility !== undefined) body.repository_visibility = repositoryVisibility;
    const data = await apiClient.put(`/projects/${enc(projectId)}/settings`, body);
    return mapProjectSettings(data);
  },

  /** POST /api/projects/:id/credentials/github — add or replace the PAT. */
  async setGithubCredential(projectId, { token, label } = {}) {
    return apiClient.post(`/projects/${enc(projectId)}/credentials/github`, {
      token,
      label: label || null,
    });
  },

  /** POST /api/projects/:id/credentials/aws — add or replace AWS keys. */
  async setAwsCredential(projectId, { accessKeyId, secretAccessKey, region, accountName } = {}) {
    return apiClient.post(`/projects/${enc(projectId)}/credentials/aws`, {
      access_key_id: accessKeyId,
      secret_access_key: secretAccessKey,
      region,
      account_name: accountName || null,
    });
  },

  /** DELETE /api/projects/:id/credentials/:provider — revoke (github_pat | aws_iam). */
  async deleteCredential(projectId, provider) {
    return apiClient.delete(`/projects/${enc(projectId)}/credentials/${enc(provider)}`);
  },
};

export default credentialsApi;
