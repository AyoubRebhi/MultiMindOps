/* ============================================================================
   workflowAnalysisApi.js — WorkflowAnalysisService.

   Single source of truth for the Workflow Analysis Dashboard
   (/workflows/:projectId/analysis). The page makes exactly ONE call —
   getAnalysis(projectId) — and distributes the aggregated result to the five
   panels. There are deliberately NO per-panel endpoints.

   Dual-surface (mirrors analysisApi.js):

     • MOCK (default, VITE_USE_MOCK !== 'false') — returns the aggregated mock
       fixture so the whole UI is buildable/demoable without a backend.

     • REAL (drop-in) — when the backend ships
           GET  /api/workflows/{projectId}/analysis   -> WorkflowAnalysis
           POST /api/workflows/{projectId}/start       -> { status, ... }
           POST /api/workflows/{projectId}/rerun       -> { status, ... }
       flip VITE_USE_MOCK=false and the same call shapes hit apiClient. The
       snake_case→camelCase mapper (mapWorkflowAnalysis) is already wired, so no
       component changes are required.

   @typedef {import('@/types/workflowAnalysis').WorkflowAnalysis} WorkflowAnalysis
   ========================================================================== */
import apiClient, { USE_MOCK } from './client';
import { mockResponse } from './mockAdapter';
import { buildMockWorkflowAnalysis } from '@/services/mock/mockWorkflowAnalysis';

/* ── Mappers (snake_case backend → camelCase UI) ──────────────────────────── */

const arr = (v) => (Array.isArray(v) ? v : []);

function mapTechItem(t = {}) {
  return { name: t.name, version: t.version || null, icon: t.icon || null, brand: !!t.brand };
}

function mapInfraGroup(list) {
  return arr(list).map((r) => ({
    service: r.service || r.name,
    reason: r.reason || r.detail || '',
    icon: r.icon || null,
  }));
}

/**
 * Normalize the raw backend payload into the WorkflowAnalysis UI shape.
 * Tolerant of partials so a still-RUNNING run renders without throwing.
 * @returns {WorkflowAnalysis}
 */
export function mapWorkflowAnalysis(api = {}, projectId) {
  const info = api.project_info || api.projectInfo || {};
  const cp = api.customer_portal || api.customerPortal || {};
  const code = api.code_analysis || api.codeAnalysis || {};
  const arch = api.architecture || {};
  const infra = api.infrastructure_recommendations || api.infrastructureRecommendations || {};
  const sec = api.security_analysis || api.securityAnalysis || {};
  const cont = api.containerization || {};

  return {
    projectInfo: {
      id: info.id || projectId,
      name: info.name || 'Untitled project',
      repositoryUrl: info.repository_url || info.repositoryUrl || '',
      branch: info.branch || null,
      logoIcon: info.logo_icon || info.logoIcon || 'fa-cube',
      brandIcon: !!(info.brand_icon ?? info.brandIcon),
    },
    customerPortal: {
      overview: cp.overview || '',
      systemPurpose: cp.system_purpose || cp.systemPurpose || '',
      inferredDomain: cp.inferred_domain || cp.inferredDomain || '',
      actors: arr(cp.actors),
      description: cp.description || '',
    },
    codeAnalysis: {
      languages: arr(code.languages).map(mapTechItem),
      frameworks: arr(code.frameworks).map(mapTechItem),
      libraries: arr(code.libraries).map(mapTechItem),
      packageManagers: arr(code.package_managers || code.packageManagers),
      buildTools: arr(code.build_tools || code.buildTools),
      repositoryCharacteristics: arr(
        code.repository_characteristics || code.repositoryCharacteristics
      ).map((c) => ({ label: c.label, value: c.value, icon: c.icon || null, ok: c.ok })),
    },
    architecture: {
      architectureType: arch.architecture_type || arch.architectureType || '',
      model: arch.model || 'HYBRID',
      confidence: arch.confidence ?? null,
      observations: arr(arch.observations),
      suggestedPattern: arch.suggested_pattern || arch.suggestedPattern || '',
      scalingAssumptions: arr(arch.scaling_assumptions || arch.scalingAssumptions),
      deploymentStrategy: arch.deployment_strategy || arch.deploymentStrategy || '',
    },
    infrastructureRecommendations: {
      awsServices: mapInfraGroup(infra.aws_services || infra.awsServices),
      compute: mapInfraGroup(infra.compute),
      storage: mapInfraGroup(infra.storage),
      networking: mapInfraGroup(infra.networking),
      observability: mapInfraGroup(infra.observability),
    },
    securityAnalysis: {
      score: sec.score ?? null,
      grade: sec.grade || null,
      summary: sec.summary || '',
      risks: arr(sec.risks).map((r, i) => ({
        id: r.id || `SEC-${String(i + 1).padStart(3, '0')}`,
        severity: r.severity || 'low',
        title: r.title || 'Security finding',
        detail: r.detail || r.description || '',
        category: r.category || 'General',
      })),
      recommendations: arr(sec.recommendations),
      hardening: arr(sec.hardening),
    },
    containerization: {
      dockerSuitability: cont.docker_suitability || cont.dockerSuitability || '',
      findings: arr(cont.findings),
      imageStrategy: arr(cont.image_strategy || cont.imageStrategy),
      notes: cont.notes || '',
    },
    status: api.status || 'DONE',
    lastUpdated: api.last_updated || api.lastUpdated || new Date().toISOString(),
    error: api.error || null,
  };
}

/* ── Service ──────────────────────────────────────────────────────────────── */

export const workflowAnalysisApi = {
  /**
   * GET /api/workflows/{projectId}/analysis — the single aggregated response.
   * @param {string} projectId
   * @returns {Promise<WorkflowAnalysis>}
   */
  async getAnalysis(projectId) {
    if (USE_MOCK) {
      return mockResponse(buildMockWorkflowAnalysis(projectId, { status: 'DONE' }));
    }
    const data = await apiClient.get(
      `/workflows/${encodeURIComponent(projectId)}/analysis`
    );
    return mapWorkflowAnalysis(data, projectId);
  },

  /**
   * POST /api/workflows/{projectId}/start — kick off a fresh workflow run.
   * Returns the (now RUNNING) aggregated analysis so the page can poll it.
   * @param {string} projectId
   * @returns {Promise<WorkflowAnalysis>}
   */
  async startWorkflow(projectId) {
    if (USE_MOCK) {
      return mockResponse(buildMockWorkflowAnalysis(projectId, { status: 'RUNNING' }));
    }
    const data = await apiClient.post(
      `/workflows/${encodeURIComponent(projectId)}/start`
    );
    return mapWorkflowAnalysis(data, projectId);
  },

  /**
   * POST /api/workflows/{projectId}/rerun — re-run analysis on the latest commit.
   * @param {string} projectId
   * @returns {Promise<WorkflowAnalysis>}
   */
  async rerunWorkflow(projectId) {
    if (USE_MOCK) {
      return mockResponse(buildMockWorkflowAnalysis(projectId, { status: 'RUNNING' }));
    }
    const data = await apiClient.post(
      `/workflows/${encodeURIComponent(projectId)}/rerun`
    );
    return mapWorkflowAnalysis(data, projectId);
  },
};

export default workflowAnalysisApi;
