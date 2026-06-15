/* ============================================================================
   projectApi.js — REAL backend integration for Projects (Project Management
   integration phase).

   Talks to the live FastAPI project router (backend/app/api/routes/projects.py).
   The caller's identity + workspace come from the JWT server-side, so create()
   only sends repo metadata. The GitHub token is WRITE-ONLY: it is sent on
   create for private repos and is never returned by any endpoint.

   Backend contract:
     POST   /projects                     -> ProjectResponse (201, bootstrap scheduled)
     GET    /projects                     -> [ProjectResponse]
     GET    /projects/:id                 -> ProjectDetailResponse (+ members/workflows)
     PATCH  /projects/:id                 -> ProjectResponse
     POST   /projects/:id/bootstrap/retry -> ProjectResponse (202, re-run analysis)
   ========================================================================== */
import apiClient from './client';

/** Map a backend ProjectResponse/ProjectDetailResponse into the UI shape. */
export function mapProject(api) {
  if (!api) return null;
  return {
    id: api.id,
    ownerId: api.owner_id,
    name: api.name,
    description: api.description || '',
    repositoryUrl: api.repository_url || '',
    repositoryVisibility: api.repository_visibility || 'public',
    // Project lifecycle status: draft | active | archived | failed.
    status: api.current_status || 'draft',
    // AI bootstrap (analysis) status: pending | analyzing | context_building |
    // ready | failed. Drives the ProjectAnalysisStatus component.
    bootstrapStatus: api.bootstrap_status || 'pending',
    bootstrapError: api.bootstrap_error || null,
    architectureType: api.architecture_type || null,
    applicationProfile: api.application_profile || null,
    metadata: api.project_metadata || {},
    createdAt: api.created_at,
    updatedAt: api.updated_at,
    // Detail-only fields (present on ProjectDetailResponse).
    members: Array.isArray(api.members) ? api.members : undefined,
    workflows: Array.isArray(api.workflows) ? api.workflows : undefined,
    artifactCount: typeof api.artifact_count === 'number' ? api.artifact_count : undefined,
  };
}

/** Map a UI create form into the backend ProjectCreate body. */
function toCreateBody(form = {}) {
  const visibility = form.repositoryVisibility === 'private' ? 'private' : 'public';
  const body = {
    name: form.name,
    description: form.description || null,
    repository_url: form.repositoryUrl || null,
    repository_visibility: visibility,
  };
  // Only attach the token for a private repo; never send it otherwise so it
  // cannot be stored unnecessarily.
  if (visibility === 'private' && form.githubToken) {
    body.github_token = form.githubToken;
  }
  return body;
}

export const projectApi = {
  /** GET /projects */
  async list() {
    const data = await apiClient.get('/projects');
    return (Array.isArray(data) ? data : []).map(mapProject);
  },

  /** GET /projects/:id */
  async getById(id) {
    const data = await apiClient.get(`/projects/${encodeURIComponent(id)}`);
    return mapProject(data);
  },

  /** POST /projects — returns the created project (analysis already scheduled). */
  async create(form) {
    const data = await apiClient.post('/projects', toCreateBody(form));
    return mapProject(data);
  },

  /** PATCH /projects/:id */
  async update(id, patch) {
    const data = await apiClient.patch(`/projects/${encodeURIComponent(id)}`, patch);
    return mapProject(data);
  },

  /** POST /projects/:id/bootstrap/retry — re-run a failed analysis. */
  async retryBootstrap(id) {
    const data = await apiClient.post(`/projects/${encodeURIComponent(id)}/bootstrap/retry`);
    return mapProject(data);
  },
};

export default projectApi;
