/* ============================================================================
   analysisApi.js — Code Analysis Agent + Security Guard Agent results.

   Two surfaces live here:

   1. REAL (project-scoped) — `getProjectAnalysis(projectId)` hits the live
      backend GET /projects/:id/analysis, which consolidates the codebase
      analysis (language/framework/runtime/deps/services/stats) and the security
      scan (score/grade/findings) the bootstrap pipeline already persisted. This
      powers the Analysis + Security tabs on the real Project Details page.

   2. MOCK (legacy, no projectId) — `getAnalysis()` / `getSecurity()` still
      return static fixtures and are consumed ONLY by the workflow-execution
      demo page (/workflows/analysis), which intentionally stays on mocks.
   ========================================================================== */
import apiClient from './client';
import { mockAnalysisResults } from '@/services/mock/mockAnalysisResults';
import { mockSecurityResults } from '@/services/mock/mockSecurityResults';
import { mockResponse } from './mockAdapter';

/** Map the backend security block into the UI security shape (camelCase). */
function mapSecurity(api) {
  if (!api) return null;
  const counts = api.counts || {};
  return {
    score: api.score ?? null,
    grade: api.grade || null,
    status: api.status || null,
    summary: api.summary || '',
    counts: {
      critical: counts.critical || 0,
      high: counts.high || 0,
      medium: counts.medium || 0,
      low: counts.low || 0,
    },
    findings: (api.findings || []).map((f, i) => ({
      id: `SEC-${String(i + 1).padStart(3, '0')}`,
      severity: f.severity || 'low',
      title: f.title || 'Security finding',
      detail: f.description || f.title || '',
      recommendation: f.recommendation || null,
      category: f.category || 'General',
    })),
    recommendations: api.recommendations || [],
  };
}

/** Map the structured application_profile object into the UI (camelCase) shape. */
function mapApplicationProfile(profile) {
  if (!profile || typeof profile !== 'object') return null;
  return {
    applicationType: profile.application_type || null,
    architecturePattern: profile.architecture_pattern || null,
    workloadProfile: profile.workload_profile || null,
    statefulness: profile.statefulness || null,
    scalabilityLevel: profile.scalability_level || null,
    entrypoints: profile.entrypoints || [],
    detectedServices: profile.detected_services || [],
  };
}

/** Map the backend GET /projects/:id/analysis payload into the UI shape. */
function mapProjectAnalysis(api, projectId) {
  if (!api) return null;
  const stats = api.stats || {};
  return {
    projectId: api.project_id || projectId,
    bootstrapStatus: api.bootstrap_status || 'pending',
    bootstrapError: api.bootstrap_error || null,
    available: !!api.analysis_available,
    language: api.language || null,
    languages: api.languages || [],
    framework: api.framework || null,
    frameworks: api.frameworks || [],
    runtime: api.runtime || null,
    dependencies: api.dependencies || [],
    services: api.services || [],
    stats: {
      projectType: stats.project_type || null,
      serviceCount: stats.service_count ?? (api.services || []).length,
      linesOfCode: stats.lines_of_code ?? null,
      hasDockerfile: !!stats.has_dockerfile,
      hasCompose: !!stats.has_compose,
      hasCi: !!stats.has_ci,
      buildSystems: stats.build_systems || [],
      devopsTools: stats.devops_tools || [],
      applicationProfile: mapApplicationProfile(stats.application_profile),
    },
    security: mapSecurity(api.security),
  };
}

export const analysisApi = {
  /* ── REAL — project-scoped ───────────────────────────────────────────── */

  /** GET /projects/:id/analysis — consolidated analysis + security. */
  async getProjectAnalysis(projectId) {
    const data = await apiClient.get(`/projects/${encodeURIComponent(projectId)}/analysis`);
    return mapProjectAnalysis(data, projectId);
  },

  /* ── MOCK — workflow-execution demo (/workflows/analysis) only ───────── */

  /** @deprecated mock-only — used by the workflow demo page. */
  async getAnalysis(projectId) {
    return mockResponse({ ...mockAnalysisResults, projectId: projectId || mockAnalysisResults.projectId });
  },

  /** @deprecated mock-only — used by the workflow demo page. */
  async getSecurity(projectId) {
    return mockResponse({ ...mockSecurityResults, projectId: projectId || mockSecurityResults.projectId });
  },
};

export default analysisApi;
