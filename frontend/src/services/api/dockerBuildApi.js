/* ============================================================================
   dockerBuildApi.js — REAL backend integration for the Docker Review → Approve
   → Build → Logs → Corrector → Fix → Rebuild sub-flow of the Docker phase.

   Everything here talks to endpoints that ALREADY exist (see PHASE 0 discovery):

     Editable artifact layer (what the build actually consumes)
       GET   /tasks/:taskId/artifacts                      → current/original/ai-patched
       PATCH /tasks/:taskId/artifacts {dockerfile}         → persist an edit
       POST  /tasks/:taskId/artifacts/apply-ai-patch       → promote suggested fix
       POST  /tasks/:taskId/artifacts/reset {artifact_type}→ restore generated

     Approval (DB Artifact.approval_state, surfaced by the docker projection)
       GET   /projects/:pid/artifacts                      → find the dockerfile row id
       POST  /projects/:pid/artifacts/:aid/approvals {action}

     Build execution + status (durable job; logs stream over WebSocket)
       POST  /execution/docker/build/:taskId               → enqueue build (+ ws_url)
       POST  /tasks/:taskId/retry-build                    → rebuild (same handler)
       GET   /execution/docker/status/:taskId              → authoritative build state

     Corrector (auto-runs on build failure; GPT-5-mini → Groq)
       GET   /corrector/:taskId                            → latest analysis
       POST  /corrector/reanalyze/:taskId                  → re-run analysis (no rebuild)

   Build LOGS are NOT polled — they stream from the FastAPI WebSocket
   `WS /ws/execution/:taskId?token=`. See dockerBuildWsUrl() + useDockerBuild.
   ========================================================================== */
import apiClient, { API_BASE_URL } from './client';
import { tokenStore } from './tokenStore';

/* ── WebSocket URL (live build logs) ──────────────────────────────────────────
   API_BASE_URL is e.g. "http://localhost:8000/api". The WS route is mounted at
   the ROOT ("/ws/execution/...", no /api prefix — app_factory mounts api_router
   with no prefix), so strip the trailing /api and swap the scheme http→ws. */
export function dockerBuildWsBase() {
  const root = String(API_BASE_URL || '').replace(/\/api\/?$/, '');
  // http→ws, https→wss. If the env value is already ws(s), this is a no-op.
  return root.replace(/^http/i, 'ws');
}

/** Build the authenticated WebSocket URL for a task's live build-log stream. */
export function dockerBuildWsUrl(taskId) {
  const token = tokenStore.getAccess();
  const q = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${dockerBuildWsBase()}/ws/execution/${encodeURIComponent(taskId)}${q}`;
}

/* ── Mappers ──────────────────────────────────────────────────────────────── */

/**
 * Map the GET /tasks/:taskId/artifacts payload into the editable Dockerfile the
 * Review/Save/Fix flow drives. This is the SAME layer the build reads
 * (`current_content` wins), so it is the source of truth for review + edit.
 */
export function mapEditableDockerfile(api = {}) {
  const df = api.dockerfile || {};
  return {
    taskId: api.task_id || null,
    // Top-level `artifacts.dockerfile` is the resolved current content; the
    // per-key object carries the comparison slots + provenance.
    content: df.current_content ?? api.artifacts?.dockerfile ?? '',
    originalContent: df.original_content || '',
    aiPatchedContent: df.ai_patched_content || null,
    version: df.version ?? null,
    userModified: !!df.user_modified,
    lastModifiedBy: df.last_modified_by || 'agent',
    updatedAt: df.updated_at || null,
  };
}

/** Normalize the backend build-status payload (authoritative, never inferred). */
export function mapBuildStatus(api = {}) {
  return {
    status: api.status || 'pending', // pending | running | success | failed | blocked | cancelled
    logs: Array.isArray(api.logs) ? api.logs : [],
    imageTag: api.image_tag || null,
    exitCode: api.exit_code ?? null,
    startedAt: api.started_at || null,
    finishedAt: api.finished_at || null,
    durationSeconds: api.duration_seconds ?? null,
    retries: api.retries || 0,
    buildNumber: api.build_number || 0,
    currentPhase: api.current_phase || '',
    failureReason: api.failure_reason || null,
    dockerCommand: api.docker_command || null,
    lastErrorLine: api.last_error_line || null,
    failedStep: api.failed_step || null,
    taskId: api.task_id || null,
    // Phase 3A — the active/last build job + its project, so the Stop button can
    // address the cancel endpoint even after a page reload.
    jobId: api.job_id || null,
    projectId: api.project_id || null,
  };
}

/** Normalize the corrector status payload (analysis is read raw, snake_case). */
export function mapCorrector(api = {}) {
  const corrector = api.corrector || {};
  return {
    taskId: api.task_id || null,
    currentPhase: api.current_phase || '',
    status: corrector.status || api.status || null,
    retryCount: api.retry_count ?? corrector.retry_count ?? 0,
    maxRetries: api.max_retries ?? corrector.max_retries ?? 3,
    available: !!(api.analysis || corrector.analysis),
    analysis: api.analysis || corrector.analysis || null,
    error: corrector.error || null,
  };
}

export const dockerBuildApi = {
  /* ── Editable artifact layer ──────────────────────────────────────────── */

  /** GET the editable Dockerfile (current/original/ai-patched/version). */
  async getEditableDockerfile(taskId) {
    const data = await apiClient.get(`/tasks/${encodeURIComponent(taskId)}/artifacts`);
    return mapEditableDockerfile(data);
  },

  /** PATCH a Dockerfile edit — backend stays the source of truth. */
  async saveDockerfile(taskId, content) {
    return apiClient.patch(`/tasks/${encodeURIComponent(taskId)}/artifacts`, {
      dockerfile: content,
    });
  },

  /** POST to promote the corrector's suggested patch into current content. */
  async applyAiPatch(taskId) {
    return apiClient.post(
      `/tasks/${encodeURIComponent(taskId)}/artifacts/apply-ai-patch`,
      {}
    );
  },

  /** POST to restore the Dockerfile to the originally generated content. */
  async resetDockerfile(taskId) {
    return apiClient.post(`/tasks/${encodeURIComponent(taskId)}/artifacts/reset`, {
      artifact_type: 'dockerfile',
    });
  },

  /* ── Approval (DB artifact) ───────────────────────────────────────────── */

  /**
   * Resolve the persisted Dockerfile artifact row id for a project (needed to
   * POST an approval). Returns null when the workflow hasn't persisted a DB
   * artifact row yet, so the caller can degrade gracefully.
   */
  async findDockerfileArtifactId(projectId) {
    const rows = await apiClient.get(
      `/projects/${encodeURIComponent(projectId)}/artifacts`
    );
    const list = Array.isArray(rows) ? rows : [];
    const match = list.find((a) => {
      const sub = String(a.artifact_subtype || '').toLowerCase();
      const type = String(a.artifact_type || '').toLowerCase();
      return sub === 'dockerfile' || type === 'dockerfile';
    });
    return match?.id || null;
  },

  /** POST an approval decision on the Dockerfile artifact row. */
  async approveDockerfile(projectId, artifactId, comment = null) {
    return apiClient.post(
      `/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(
        artifactId
      )}/approvals`,
      { action: 'approve', comment }
    );
  },

  /* ── Build execution + status ─────────────────────────────────────────── */

  /**
   * POST to enqueue a Docker build. Returns the build descriptor
   * ({ status, ws_url, job_id, build_number, image_tag, execution_session_id }).
   * A blocked pre-build gate throws a 422 — the caller surfaces the reason.
   */
  async startBuild(taskId) {
    return apiClient.post(
      `/execution/docker/build/${encodeURIComponent(taskId)}`,
      {}
    );
  },

  /** POST a rebuild (same backend handler, latest saved artifacts). */
  async rebuild(taskId) {
    return apiClient.post(`/tasks/${encodeURIComponent(taskId)}/retry-build`, {});
  },

  /** GET the authoritative persisted build state (status + buffered logs). */
  async getBuildStatus(taskId) {
    const data = await apiClient.get(
      `/execution/docker/status/${encodeURIComponent(taskId)}`
    );
    return mapBuildStatus(data);
  },

  /* ── Corrector ────────────────────────────────────────────────────────── */

  /** GET the latest corrector analysis for a failed build. */
  async getCorrector(taskId) {
    const data = await apiClient.get(`/corrector/${encodeURIComponent(taskId)}`);
    return mapCorrector(data);
  },

  /** POST to re-run corrector analysis on the stored logs (no rebuild). */
  async reanalyze(taskId) {
    return apiClient.post(
      `/corrector/reanalyze/${encodeURIComponent(taskId)}`,
      {}
    );
  },
};

export default dockerBuildApi;
