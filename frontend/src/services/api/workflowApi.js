/* ============================================================================
   workflowApi.js — REAL backend integration for the Workflows page.

   Talks to the live FastAPI workflow surface. Visibility is enforced
   server-side by role (ADMIN sees all; a DEVOPS_ENGINEER sees only the
   workflows they launched), so this module just shapes the response.

   Backend contract:
     GET /workflows                  -> [WorkflowSummary]   (role-aware)
     GET /workflows/:id              -> WorkflowSummary      (resume: status+phase)
     GET /workflows/:id/analysis     -> WorkflowAnalysis     (5 aggregated sections)
     GET /projects/:projectId/workflows -> [WorkflowResponse] (project-scoped)

   See backend/app/api/routes/workflows.py + schemas/workflow.py +
   schemas/workflow_analysis.py.
   ========================================================================== */
import apiClient from './client';

/** Map a backend WorkflowSummary into the shape the Workflows UI consumes. */
export function mapWorkflowSummary(api) {
  if (!api) return null;
  const completed = Number(api.completed_phases) || 0;
  const total = Number(api.total_phases) || 0;
  return {
    id: api.id,
    projectId: api.project_id,
    projectName: api.project_name || 'Unknown project',
    // The backend has no first-class workflow name; present each run by its
    // project so the card has a meaningful title.
    name: api.project_name ? `${api.project_name} pipeline` : 'Workflow run',
    ownerId: api.started_by_id || null,
    ownerName: api.started_by_name || 'Unknown',
    status: api.status,
    currentPhase: api.current_phase || null,
    completedPhases: completed,
    totalPhases: total,
    progress: total > 0 ? Math.round((completed / total) * 100) : 0,
    createdAt: api.created_at,
    updatedAt: api.updated_at,
  };
}

/** Map the project-scoped WorkflowResponse (full row) into the UI shape. */
function mapProjectWorkflow(api) {
  if (!api) return null;
  const phases = api.phases_state || {};
  const DONE = ['completed', 'completed_with_fallback', 'completed_no_files'];
  const entries = Object.values(phases).filter((e) => e && typeof e === 'object');
  const total = entries.length;
  const completed = entries.filter((e) => DONE.includes(e.status)).length;
  return {
    id: api.id,
    projectId: api.project_id,
    projectName: undefined,
    name: 'Workflow run',
    ownerId: api.started_by || null,
    ownerName: undefined,
    status: api.status,
    currentPhase: api.current_phase || null,
    completedPhases: completed,
    totalPhases: total,
    progress: total > 0 ? Math.round((completed / total) * 100) : 0,
    createdAt: api.created_at,
    updatedAt: api.updated_at,
  };
}

/* ── Analysis-phase mapper (backend 5-section DTO → panel camelCase shape) ──── */

const arr = (v) => (Array.isArray(v) ? v : []);
const tech = (list) => arr(list).map((t) => ({ name: t.name, version: t.version || null }));
const infraGroup = (list) =>
  arr(list).map((r) => ({ service: r.service, reason: r.reason || '' }));

/** Map application type/pattern to the architecture panel's model chip. */
function archModel(applicationType, pattern) {
  const t = `${applicationType || ''} ${pattern || ''}`.toLowerCase();
  if (t.includes('microservice')) return 'MICROSERVICES';
  if (t.includes('serverless') || t.includes('lambda')) return 'SERVERLESS';
  if (t.includes('monolith')) return 'MONOLITH';
  return 'HYBRID';
}

/** Build the customer-portal "description" line from the application profile. */
function profileDescription(cp) {
  const bits = [];
  if (cp.workload_profile) bits.push(`Workload: ${cp.workload_profile}`);
  if (cp.statefulness) bits.push(cp.statefulness);
  if (cp.scalability_level) bits.push(`Scalability: ${cp.scalability_level}`);
  return bits.join(' · ');
}

/**
 * Normalize the backend WorkflowAnalysisResponse into the shape the existing
 * analysis panels consume (the same camelCase contract as the project-scoped
 * dashboard's mapper). Tolerant of partials so a still-RUNNING run renders.
 */
export function mapWorkflowPhaseAnalysis(api = {}) {
  const info = api.project_info || {};
  const cp = api.customer_portal || {};
  const code = api.code_analysis || {};
  const arch = api.architecture_intelligence || {};
  const infra = api.infrastructure_recommendations || {};
  const sc = api.security_containerization || {};
  const sec = sc.security || {};
  const cont = sc.containerization || {};

  const systemPurpose = [cp.application_type, cp.architecture_pattern]
    .filter(Boolean)
    .join(' · ');

  return {
    workflowId: api.workflow_id,
    projectId: api.project_id,
    projectInfo: {
      id: info.id || api.project_id,
      name: info.name || 'Untitled project',
      repositoryUrl: info.repository_url || '',
      branch: info.branch || null,
      logoIcon: info.logo_icon || 'fa-cube',
      brandIcon: !!info.brand_icon,
    },
    customerPortal: {
      overview: cp.application_purpose || '',
      systemPurpose,
      inferredDomain: cp.application_type || '',
      actors: [],
      description: profileDescription(cp),
    },
    codeAnalysis: {
      languages: tech(code.languages),
      frameworks: tech(code.frameworks),
      libraries: tech(code.libraries),
      packageManagers: arr(code.package_managers),
      buildTools: arr(code.build_tools),
      repositoryCharacteristics: arr(code.repository_insights).map((c) => ({
        label: c.label,
        value: c.value,
        ok: c.ok,
      })),
    },
    architecture: {
      architectureType: arch.architecture_type || '',
      model: archModel(arch.architecture_type || cp.application_type, arch.architecture_pattern),
      confidence: null,
      observations: arr(arch.observations),
      suggestedPattern: arch.architecture_pattern || '',
      scalingAssumptions: arr(arch.entry_points).map((e) => `Entry point: ${e}`),
      deploymentStrategy: arr(arch.deployment_recommendations).join(' '),
    },
    infrastructureRecommendations: {
      awsServices: infraGroup(infra.aws_services),
      compute: infraGroup(infra.compute),
      storage: infraGroup(infra.storage),
      networking: infraGroup(infra.networking),
      observability: infraGroup(infra.observability),
    },
    securityAnalysis: {
      score: sec.score ?? null,
      grade: sec.grade || null,
      summary: sec.summary || '',
      risks: arr(sec.findings).map((f, i) => ({
        id: `SEC-${String(i + 1).padStart(3, '0')}`,
        severity: f.severity || 'low',
        title: f.title || 'Security finding',
        detail: f.description || '',
        category: f.category || 'General',
      })),
      recommendations: arr(sec.recommendations),
      hardening: [],
    },
    containerization: {
      dockerSuitability: cont.docker_suitability || '',
      findings: arr(cont.findings),
      imageStrategy: arr(cont.image_strategy),
      notes: cont.notes || '',
    },
    status: api.status || 'DONE',
    lastUpdated: api.last_updated || null,
  };
}

/* ── Architecture-planning mappers (backend plan DTO → card shape) ──────────── */

/**
 * Map ONE backend architecture-plan entry (from ArchitectureDecisionAgent) into
 * the shape the Architecture Planning cards + comparison table consume. Faithful
 * to the backend — every field shown is read straight from the response, never
 * synthesized. Tolerant of partials so a degraded plan still renders.
 */
export function mapArchitecturePlan(p = {}, { recommendedPlan, selectedPlanId } = {}) {
  const infra = p.infrastructure || {};
  const compute = infra.compute || {};
  const database = infra.database || {};
  return {
    id: p.id,
    title: p.title || p.id || 'Architecture plan',
    description: p.description || '',
    // Cost
    monthlyCost: typeof p.monthly_cost === 'number' ? p.monthly_cost : null,
    yearlyCost: typeof p.yearly_cost === 'number' ? p.yearly_cost : null,
    costBreakdown: p.cost_breakdown || {},
    costProfile: p.cost_profile || null,
    // Ratings / characteristics
    scalabilityTier: p.scalability_tier || null,
    availabilityLevel: p.availability_level || null,
    complexity: p.estimated_complexity || null,
    // Services + reasoning
    awsServices: arr(p.aws_services),
    tradeoffs: arr(p.tradeoffs),
    optimizationTips: arr(p.optimization_tips),
    assumptions: arr(p.assumptions),
    // Architecture pattern / deployment model / runtime (from the blueprint)
    architecture: {
      style: infra.architecture_style || null,
      computeType: compute.type || null,
      runtime: compute.runtime || compute.instance_type || compute.node_type || null,
      deployment: database.deployment || null,
      databaseEngine: database.engine || null,
    },
    recommended: !!p.id && p.id === recommendedPlan,
    selected: !!p.id && p.id === selectedPlanId,
  };
}

/**
 * Map the GET .../architecture-decision payload into the planning-view model.
 */
export function mapArchitectureDecision(api = {}) {
  const recommendedPlan = api.recommended_plan || null;
  const selectedPlanId = api.selected_plan_id || null;
  return {
    workflowId: api.workflow_id || null,
    currentPhase: api.current_phase || null,
    status: api.status || null,
    recommendedPlan,
    selectedPlanId,
    plans: arr(api.plans).map((p) =>
      mapArchitecturePlan(p, { recommendedPlan, selectedPlanId })
    ),
  };
}

/* ── Docker-phase mapper (backend DockerPhaseResponse → camelCase view) ─────── */

/** Normalize one validation/generation issue. */
function dockerIssue(i = {}) {
  return {
    rule: i.rule || null,
    message: i.message || '',
    severity: i.severity || null,
    sectionId: i.section_id || null,
  };
}

/**
 * Map the GET .../docker projection into the Docker-phase view model. Faithful
 * to the backend — every field is read straight from the persisted DOCKER-phase
 * state (generated Dockerfile + metadata + validation + corrector). Tolerant of
 * partials so a still-generating / not-yet-reached run renders.
 */
export function mapDockerPhase(api = {}) {
  const df = api.dockerfile || null;
  const meta = api.metadata || {};
  const val = api.validation || {};
  const corr = api.corrector || {};
  return {
    workflowId: api.workflow_id || null,
    projectId: api.project_id || null,
    taskId: api.task_id || null,
    currentPhase: api.current_phase || null,
    status: api.status || null,
    dockerPhaseStatus: api.docker_phase_status || null,
    generated: !!api.generated,
    dockerfile: df
      ? {
          filename: df.filename || 'Dockerfile',
          content: df.content || '',
          originalContent: df.original_content || '',
          edited: !!df.edited,
          version: df.version ?? null,
          approvalState: df.approval_state || null,
          validationStatus: df.validation_status || null,
        }
      : null,
    metadata: {
      detectedRuntime: meta.detected_runtime || null,
      language: meta.language || null,
      framework: meta.framework || null,
      baseImage: meta.base_image || null,
      port: meta.port || null,
      buildStrategy: meta.build_strategy || null,
      containerType: meta.container_type || null,
      blueprintId: meta.blueprint_id || null,
      usedLlm: meta.used_llm !== false,
      fallbackUsed: !!meta.fallback_used,
      generationMode: meta.generation_mode || 'llm',
    },
    validation: {
      status: val.status || 'not_run',
      valid: val.valid !== false,
      errors: arr(val.errors).map(dockerIssue),
      warnings: arr(val.warnings).map(dockerIssue),
      recommendations: arr(val.recommendations).map(dockerIssue),
    },
    corrector: {
      available: !!corr.available,
      status: corr.status || null,
      retryCount: corr.retry_count || 0,
      maxRetries: corr.max_retries || 3,
      analysis: corr.analysis || null,
      correctedDockerfile: corr.corrected_dockerfile || null,
    },
    hasDockerignore: !!api.has_dockerignore,
    hasCompose: !!api.has_compose,
  };
}

export const workflowApi = {
  /** GET /workflows — role-aware list of workflow summaries. */
  async list() {
    const data = await apiClient.get('/workflows');
    return (Array.isArray(data) ? data : []).map(mapWorkflowSummary);
  },

  /** GET /workflows/:id — one summary so the UI can resume from its phase. */
  async get(workflowId) {
    const data = await apiClient.get(`/workflows/${encodeURIComponent(workflowId)}`);
    return mapWorkflowSummary(data);
  },

  /** GET /workflows/:id/analysis — the single aggregated Analysis payload. */
  async getAnalysis(workflowId) {
    const data = await apiClient.get(
      `/workflows/${encodeURIComponent(workflowId)}/analysis`
    );
    return mapWorkflowPhaseAnalysis(data);
  },

  /** GET /projects/:projectId/workflows — workflows for one project. */
  async listByProject(projectId) {
    const data = await apiClient.get(
      `/projects/${encodeURIComponent(projectId)}/workflows`
    );
    return (Array.isArray(data) ? data : []).map(mapProjectWorkflow);
  },

  /**
   * GET /projects/:projectId/workflows/:workflowId/architecture-decision —
   * the AI-generated architecture plans (+ recommended + selected). The backend
   * returns 404 until the architecture-decision phase has produced plans, which
   * the caller surfaces as a "no plans yet" state.
   */
  async getArchitectureDecision(projectId, workflowId) {
    const data = await apiClient.get(
      `/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(
        workflowId
      )}/architecture-decision`
    );
    return mapArchitectureDecision(data);
  },

  /**
   * POST /projects/:projectId/workflows/:workflowId/select-plan — persist the
   * engineer's chosen plan. The BACKEND owns the transition (records
   * PLAN_SELECTED, promotes the plan + cost, unblocks Terraform Generation);
   * the frontend never mutates workflow state itself. Returns the updated
   * phase-run response ({ current_phase, status, phases_state, ... }).
   */
  async selectPlan(projectId, workflowId, planId) {
    return apiClient.post(
      `/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(
        workflowId
      )}/select-plan`,
      { plan_id: planId }
    );
  },

  /**
   * GET /projects/:projectId/workflows/:workflowId/docker — the aggregated
   * Docker-Generation payload (generated Dockerfile + metadata + validation +
   * corrector + approval provenance), in ONE read. Returns 200 with
   * `generated: false` when the workflow hasn't reached the DOCKER phase yet, so
   * the caller can show an honest "not generated" state instead of a 404.
   */
  async getDockerPhase(projectId, workflowId) {
    const data = await apiClient.get(
      `/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(
        workflowId
      )}/docker`
    );
    return mapDockerPhase(data);
  },

  /**
   * POST /projects/:projectId/workflows/:workflowId/phases/DOCKER — run (or
   * rerun) the Docker Generation phase via InfrastructureAgent (GPT-5-mini →
   * Groq). The BACKEND owns the transition + persistence; the frontend never
   * mutates workflow state. The phase-completion contract means this never 500s
   * for an LLM problem — it degrades to deterministic artifacts. Returns the
   * phase-run response ({ current_phase, status, phases_state, ... }).
   */
  async runDockerPhase(projectId, workflowId) {
    return apiClient.post(
      `/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(
        workflowId
      )}/phases/DOCKER`,
      {}
    );
  },
};

export default workflowApi;
