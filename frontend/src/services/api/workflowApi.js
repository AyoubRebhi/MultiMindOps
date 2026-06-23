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
import apiClient, { API_BASE_URL } from './client';
import { tokenStore } from './tokenStore';

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

/* ── GitHub Actions Generation phase mapper ─────────────────────────────────── */

/**
 * Map the GET .../github-actions projection into the deployment-phase view model.
 * Faithful to the backend — every field is read straight from the persisted
 * GITHUB_ACTIONS_GENERATION state (rendered deploy.yml + deployment context +
 * YAML validation). Tolerant of partials so a not-yet-reached run renders.
 */
export function mapGithubActionsPhase(api = {}) {
  const ctx = api.deployment_context || {};
  const val = api.validation || {};
  const wf = api.workflow_file || null;
  return {
    workflowId: api.workflow_id || null,
    projectId: api.project_id || null,
    taskId: api.task_id || null,
    currentPhase: api.current_phase || null,
    status: api.status || null,
    phaseStatus: api.phase_status || null,
    generated: !!api.generated,
    deploymentTarget: api.deployment_target || ctx.deployment_target || null,
    template: api.template || null,
    enrichmentApplied: !!api.enrichment_applied,
    deploymentContext: {
      cloudProvider: ctx.cloud_provider || 'aws',
      deploymentTarget: ctx.deployment_target || null,
      awsRegion: ctx.aws_region || null,
      projectName: ctx.project_name || null,
      repositoryName: ctx.repository_name || null,
      clusterName: ctx.cluster_name || null,
      serviceName: ctx.service_name || null,
      functionName: ctx.function_name || null,
      containerPort: ctx.container_port ?? null,
      terraformDirectory: ctx.terraform_directory || null,
      dockerArtifacts: arr(ctx.docker_artifacts),
      terraformArtifacts: arr(ctx.terraform_artifacts),
    },
    validation: {
      status: val.status || 'not_run',
      valid: val.valid !== false,
      errors: arr(val.errors),
      warnings: arr(val.warnings),
    },
    workflowFile: wf
      ? {
          path: wf.path || '.github/workflows/deploy.yml',
          content: wf.content || '',
          version: wf.version ?? null,
          approvalState: wf.approval_state || null,
          validationStatus: wf.validation_status || null,
        }
      : null,
    infrastructureSummary: api.infrastructure_summary || {},
  };
}

/* ── Terraform-phase mappers (Phase 2A: Generation only) ────────────────────── */

/**
 * Map the project-scoped WorkflowResponse, PRESERVING the raw `phases_state`.
 * The Terraform surface reads phase status exclusively from this map (the
 * resume summary from GET /workflows/:id has no phases_state).
 */
export function mapWorkflowDetail(api) {
  if (!api) return null;
  return {
    id: api.id,
    projectId: api.project_id,
    currentPhase: api.current_phase || null,
    status: api.status,
    phasesState: api.phases_state || {},
    updatedAt: api.updated_at || null,
  };
}

// Canonical TerraformAgent state keys → on-disk filenames. Mirrors the backend
// _TERRAFORM_KEY_TO_FILENAME map (artifact_persistence_service.py) so the viewer
// shows real filenames regardless of whether the subtype was persisted as the
// canonical key (`terraform_main`) or the resolved filename (`main.tf`).
const TF_SUBTYPE_TO_FILENAME = {
  terraform_providers: 'providers.tf',
  terraform_main: 'main.tf',
  terraform_vpc: 'vpc.tf',
  terraform_eks: 'eks.tf',
  terraform_ecs: 'ecs.tf',
  terraform_variables: 'variables.tf',
  terraform_tfvars: 'terraform.tfvars',
  terraform_outputs: 'outputs.tf',
  terraform_backend: 'backend.tf',
};

function tfFilename(subtype) {
  if (!subtype) return null;
  const low = String(subtype).toLowerCase();
  if (TF_SUBTYPE_TO_FILENAME[low]) return TF_SUBTYPE_TO_FILENAME[low];
  if (/\.(tf|tfvars|tfstate)$/.test(low)) return subtype;
  if (low.startsWith('terraform_')) return `${subtype.slice('terraform_'.length)}.tf`;
  return subtype;
}

// Preferred default tab order: main → variables → outputs → providers, rest after.
const TF_FILE_ORDER = [
  'main.tf', 'variables.tf', 'outputs.tf', 'providers.tf', 'terraform.tfvars', 'backend.tf',
];
function tfOrder(name) {
  const i = TF_FILE_ORDER.indexOf(name);
  return i === -1 ? TF_FILE_ORDER.length + 1 : i;
}

/**
 * Map the project artifacts list (ArtifactResponse[]) into the
 * <TerraformFileViewer /> shape, keeping ONLY artifact_type === 'terraform'
 * (the generated .tf files). Filenames are normalized from the stored subtype
 * and ordered for a readable default tab. One terraform row exists per subtype
 * per project (the upsert dedupes), so no workflow filter is needed.
 */
export function mapTerraformArtifacts(list = []) {
  return arr(list)
    .filter((a) => a && a.artifact_type === 'terraform')
    .map((a) => {
      const name = tfFilename(a.artifact_subtype) || a.artifact_subtype || 'main.tf';
      const content = a.content || '';
      return {
        id: a.id,
        name,
        content,
        lines: content ? content.replace(/\n$/, '').split('\n').length : 0,
        summary: a.generated_by_agent || 'terraform',
        version: a.version ?? null,
        approvalState: a.approval_state || null,
        validationStatus: a.validation_status || null,
        updatedAt: a.updated_at || null,
      };
    })
    .sort((x, y) => tfOrder(x.name) - tfOrder(y.name) || x.name.localeCompare(y.name));
}

/* ── Terraform Validation (Phase 2B) ────────────────────────────────────────── */

/**
 * Normalize a WorkflowPhaseRunResponse (the POST .../phases/:phase reply). The
 * Terraform Validation surface needs `taskId` from here to open the live-log
 * WebSocket — the GET workflow row does NOT expose it.
 */
export function mapPhaseRun(api = {}) {
  return {
    workflowId: api.workflow_id || null,
    taskId: api.task_id || null,
    currentPhase: api.current_phase || null,
    status: api.status || null,
    phasesState: api.phases_state || {},
  };
}

/**
 * Extract the persisted Terraform validation report from the project artifacts
 * list. The backend writes ONE `validation_report` artifact
 * (subtype `terraform_validation.json`) whose content is the JSON
 * `{ ok, error, failure_classification, results:[{step, ok, returncode, output}] }`.
 * Returns null when no report exists yet (validation hasn't run). Defensive: a
 * malformed/empty body degrades to the artifact's `validation_status`.
 */
export function mapTerraformValidationReport(list = []) {
  const row = arr(list).find(
    (a) =>
      a &&
      a.artifact_type === 'validation_report' &&
      String(a.artifact_subtype || '').toLowerCase().includes('terraform_validation')
  );
  if (!row) return null;
  let parsed = null;
  try {
    parsed = JSON.parse(row.content || '');
  } catch {
    parsed = null;
  }
  const steps = arr(parsed?.results).map((r) => ({
    step: r.step || r.label || 'step',
    ok: r.ok !== false,
    returnCode: r.returncode ?? r.return_code ?? null,
    output: r.output || '',
  }));
  return {
    id: row.id,
    validationStatus: row.validation_status || (parsed?.ok ? 'passed' : 'failed'),
    ok: parsed ? !!parsed.ok : row.validation_status === 'passed',
    error: parsed?.error || null,
    failureClassification: parsed?.failure_classification || null,
    steps,
    updatedAt: row.updated_at || null,
    raw: row.content || '',
  };
}

/* ── Terraform Plan (Phase 2C) ──────────────────────────────────────────────── */

/**
 * Normalize a backend Infrastructure Summary (the categorized resource breakdown
 * `terraform show -json` produces after a successful plan) into a stable
 * camelCase shape the cards consume. The SAME backend shape is emitted in two
 * places — embedded in `phases_state.TERRAFORM_PLAN.infrastructure_summary` and
 * as the standalone `infrastructure_summary.json` artifact — so this one
 * normalizer serves both. Tolerant of partials; returns null for a non-object.
 *
 *   backend: { total_resources, resource_counts, categories:[
 *               { name, items:[ { type, label, count } ] } ] }
 */
export function normalizeInfrastructureSummary(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const categories = arr(raw.categories)
    .map((c) => ({
      name: c.name || 'Other',
      items: arr(c.items).map((i) => ({
        type: i.type || '',
        label: i.label || i.type || 'Resource',
        count: Number(i.count) || 0,
      })),
    }))
    .filter((c) => c.items.length > 0);
  if (!categories.length && typeof raw.total_resources !== 'number') return null;
  const total =
    typeof raw.total_resources === 'number'
      ? raw.total_resources
      : categories.reduce(
          (s, c) => s + c.items.reduce((t, i) => t + i.count, 0),
          0
        );
  return { totalResources: total, categories };
}

/**
 * Extract the persisted `infrastructure_summary` artifact (subtype
 * `infrastructure_summary.json`) from the project artifacts list. This is the
 * FALLBACK source — callers prefer the copy embedded in
 * `phases_state.TERRAFORM_PLAN.infrastructure_summary` (no second parse) and use
 * this only when the phase entry has none. Returns null when no plan has run.
 */
export function mapInfrastructureSummary(list = []) {
  const row = arr(list).find(
    (a) => a && a.artifact_type === 'infrastructure_summary'
  );
  if (!row) return null;
  try {
    return normalizeInfrastructureSummary(JSON.parse(row.content || ''));
  } catch {
    return null;
  }
}

/**
 * Extract the raw `plan.json` (terraform show -json) artifact the backend writes
 * after a successful plan (artifact_type `terraform_plan`, subtype `plan.json`).
 * Returns the machine-readable plan text + provenance, or null when no plan has
 * run yet. The opaque binary `tfplan` stays on the filesystem and is not exposed.
 */
export function mapTerraformPlanArtifact(list = []) {
  const row = arr(list).find(
    (a) =>
      a &&
      a.artifact_type === 'terraform_plan' &&
      String(a.artifact_subtype || '').toLowerCase().includes('plan.json')
  );
  if (!row) return null;
  const content = row.content || '';
  return {
    id: row.id,
    content,
    lines: content ? content.replace(/\n$/, '').split('\n').length : 0,
    updatedAt: row.updated_at || null,
  };
}

/* ── WebSocket URL (live Terraform validation logs) ───────────────────────────
   The WS route is mounted at the ROOT ("/ws/terraform/...", no /api prefix), so
   strip the trailing /api from API_BASE_URL and swap the scheme http→ws. This
   is the SAME streaming infrastructure as the Docker build socket, namespaced by
   job phase (`terraform_validate`). Mirrors dockerBuildWsUrl(). */
function terraformWsBase() {
  const root = String(API_BASE_URL || '').replace(/\/api\/?$/, '');
  return root.replace(/^http/i, 'ws');
}

/**
 * Authenticated WebSocket URL for a task's live Terraform log stream. The same
 * route serves BOTH Terraform durable phases, namespaced by `jobPhase`:
 * `terraform_validate` (default) and `terraform_plan`. Same socket, same frames.
 */
export function terraformValidateWsUrl(taskId, jobPhase = 'terraform_validate') {
  const token = tokenStore.getAccess();
  const q = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${terraformWsBase()}/ws/terraform/${encodeURIComponent(
    taskId
  )}/${encodeURIComponent(jobPhase)}${q}`;
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

  /**
   * GET /projects/:projectId/workflows/:workflowId/github-actions — the
   * aggregated GitHub Actions Generation payload (rendered deploy.yml +
   * deployment context + YAML validation), in ONE read. Returns 200 with
   * `generated: false` when the workflow hasn't reached the phase yet.
   */
  async getGithubActionsPhase(projectId, workflowId) {
    const data = await apiClient.get(
      `/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(
        workflowId
      )}/github-actions`
    );
    return mapGithubActionsPhase(data);
  },

  /**
   * POST /projects/:projectId/workflows/:workflowId/phases/GITHUB_ACTIONS_GENERATION —
   * render the deploy workflow from the validated Docker + Terraform artifacts +
   * the selected architecture decision. The deployment target is derived from the
   * blueprint (never asked). The BACKEND owns the transition + persistence; the
   * frontend never mutates workflow state. Prerequisite (server-side):
   * PLAN_SELECTED + DOCKER + TERRAFORM_GENERATION must be completed. Returns the
   * mapped phase-run response ({ taskId, currentPhase, status, phasesState }).
   */
  async runGithubActionsPhase(projectId, workflowId) {
    const data = await apiClient.post(
      `/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(
        workflowId
      )}/phases/GITHUB_ACTIONS_GENERATION`,
      {}
    );
    return mapPhaseRun(data);
  },

  /**
   * GET /projects/:projectId/workflows/:workflowId — the full workflow row,
   * including `phases_state`. The Terraform surface reads its phase status
   * exclusively from this (the resume summary has no phases_state).
   */
  async getProjectWorkflow(projectId, workflowId) {
    const data = await apiClient.get(
      `/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(workflowId)}`
    );
    return mapWorkflowDetail(data);
  },

  /**
   * GET /projects/:projectId/artifacts — the raw persisted-artifacts list (with
   * content). Fetched ONCE per Terraform read; callers derive the generated .tf
   * files (mapTerraformArtifacts) AND the validation report
   * (mapTerraformValidationReport) from this single payload.
   */
  async getProjectArtifacts(projectId) {
    const data = await apiClient.get(
      `/projects/${encodeURIComponent(projectId)}/artifacts`
    );
    return Array.isArray(data) ? data : [];
  },

  /**
   * POST /projects/:projectId/workflows/:workflowId/phases/:phase — run a
   * Terraform pipeline phase. Phase 2A only ever passes 'TERRAFORM_GENERATION'
   * (LLM → DB → rehydrate; runs inline and returns the phase-run response with
   * the updated phases_state). The BACKEND owns the transition + persistence;
   * the frontend never mutates workflow state. Prerequisite (enforced server-
   * side): a plan must be selected (PLAN_SELECTED) — Docker is NOT required.
   */
  async runTerraformPhase(projectId, workflowId, phase = 'TERRAFORM_GENERATION') {
    return apiClient.post(
      `/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(
        workflowId
      )}/phases/${encodeURIComponent(phase)}`,
      {}
    );
  },

  /**
   * POST /projects/:projectId/workflows/:workflowId/phases/TERRAFORM_VALIDATION —
   * enqueue the durable Terraform validation job (terraform init + validate,
   * streamed). The BACKEND owns the transition: it records
   * `phases_state.TERRAFORM_VALIDATION = running` and returns the `task_id` the
   * caller uses to open the live-log WebSocket (terraformValidateWsUrl). When the
   * job finishes, the worker writes the final status + a `validation_report`
   * artifact. Prerequisite (server-side): TERRAFORM_GENERATION must be completed.
   * Returns the mapped phase-run response ({ taskId, currentPhase, status,
   * phasesState }).
   */
  async runTerraformValidation(projectId, workflowId) {
    const data = await apiClient.post(
      `/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(
        workflowId
      )}/phases/TERRAFORM_VALIDATION`,
      {}
    );
    return mapPhaseRun(data);
  },

  /**
   * POST /projects/:projectId/workflows/:workflowId/phases/TERRAFORM_PLAN —
   * enqueue the durable Terraform plan job (terraform init + plan -out=tfplan,
   * streamed). Mirrors validation EXACTLY: the BACKEND records
   * `phases_state.TERRAFORM_PLAN = running` and returns the `task_id` the caller
   * uses to open the live-log WebSocket (terraformValidateWsUrl(taskId,
   * 'terraform_plan')). On success the worker writes the raw `plan.json` +
   * `infrastructure_summary` artifacts and embeds the categorized summary into
   * the TERRAFORM_PLAN phase entry. Prerequisite (server-side):
   * TERRAFORM_VALIDATION (after TERRAFORM_GENERATION) must be completed. Returns
   * the mapped phase-run response ({ taskId, currentPhase, status, phasesState }).
   */
  async runTerraformPlan(projectId, workflowId) {
    const data = await apiClient.post(
      `/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(
        workflowId
      )}/phases/TERRAFORM_PLAN`,
      {}
    );
    return mapPhaseRun(data);
  },
};

export default workflowApi;
