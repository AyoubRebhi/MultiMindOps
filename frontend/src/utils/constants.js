/* ============================================================================
   constants.js — shared, presentation-level constants for the platform.
   Kept free of business logic; these are labels, icons, ordering and the
   metadata used to render statuses consistently across pages/components.
   ========================================================================== */

/** App-wide identity (used in the sidebar logo, page titles, etc.). */
export const APP_NAME = 'MultiMinds AI';
export const APP_TAGLINE = 'AI Cloud Engineering Platform';

/**
 * Sidebar navigation. Grouped into sections; each item maps to a route.
 * `end` forces exact matching for the index route so it isn't always active.
 */
export const NAV_SECTIONS = [
  {
    title: 'Platform',
    items: [
      { label: 'Dashboard', icon: 'fa-gauge-high', to: '/', end: true },
      { label: 'Projects', icon: 'fa-folder-tree', to: '/projects' },
      { label: 'Workflows', icon: 'fa-diagram-project', to: '/workflows' },
    ],
  },
  {
    title: 'Engineering',
    items: [
      { label: 'Architecture', icon: 'fa-sitemap', to: '/architecture' },
      {
        label: 'Infrastructure',
        icon: 'fa-server',
        to: '/infrastructure',
        badge: 'IaC',
      },
    ],
  },
  {
    title: 'Workspace',
    items: [{ label: 'Settings', icon: 'fa-gear', to: '/settings' }],
  },
];

/**
 * Ordered workflow pipeline phases, mirroring the backend roadmap. Used by the
 * workflow timeline, project details and the phase status badge.
 */
export const WORKFLOW_PHASES = [
  {
    key: 'REPO_ANALYSIS',
    label: 'Repository Analysis',
    icon: 'fa-magnifying-glass-chart',
    description: 'Detect stack, services, dependencies and build context.',
  },
  {
    key: 'ARCHITECTURE',
    label: 'Architecture Planning',
    icon: 'fa-sitemap',
    description: 'Propose and compare candidate cloud architectures.',
  },
  {
    key: 'DOCKER_GENERATION',
    label: 'Container Build',
    icon: 'fa-docker',
    brand: true,
    description: 'Generate, validate and build Dockerfiles per service.',
  },
  {
    key: 'COST_ESTIMATION',
    label: 'Cost Estimation',
    icon: 'fa-coins',
    description: 'Estimate monthly cloud spend and optimization tips.',
  },
  {
    key: 'TERRAFORM_GENERATION',
    label: 'Terraform Provisioning',
    icon: 'fa-cubes',
    description: 'Generate, validate and plan Terraform infrastructure.',
  },
  {
    key: 'K8S_GENERATION',
    label: 'Kubernetes Manifests',
    icon: 'fa-dharmachakra',
    description: 'Render deployment, service and ingress manifests.',
  },
  {
    key: 'CORRECTOR_REVIEW',
    label: 'AI Corrector Review',
    icon: 'fa-wand-magic-sparkles',
    description: 'Diagnose failures and propose remediation for review.',
  },
  {
    key: 'DEPLOY',
    label: 'Deployment',
    icon: 'fa-rocket',
    description: 'Apply infrastructure and roll out the workload.',
  },
];

/** Lookup the phase metadata by key (falls back to a generic descriptor). */
export function getPhaseMeta(key) {
  return (
    WORKFLOW_PHASES.find((p) => p.key === key) || {
      key,
      label: key,
      icon: 'fa-circle-nodes',
      description: '',
    }
  );
}

/**
 * Display metadata for the CANONICAL backend workflow phases — the phase names
 * the engine records in ``Workflow.current_phase`` / ``phases_state`` (see
 * backend/app/services/core/workflow_orchestration_service.py). These differ
 * from the roadmap keys in WORKFLOW_PHASES above, so the Workflows page resolves
 * the live phase through this map.
 */
export const BACKEND_WORKFLOW_PHASE_META = {
  ARCHITECTURE_DECISION: { label: 'Architecture Decision', icon: 'fa-sitemap' },
  PLAN_SELECTED: { label: 'Plan Selected', icon: 'fa-clipboard-check' },
  DOCKER: { label: 'Docker Generation', icon: 'fa-docker', brand: true },
  DOCKER_BUILD: { label: 'Docker Build', icon: 'fa-hammer' },
  TERRAFORM_GENERATION: { label: 'Terraform Generation', icon: 'fa-cubes' },
  TERRAFORM_VALIDATION: { label: 'Terraform Validation', icon: 'fa-clipboard-check' },
  TERRAFORM_PLAN: { label: 'Terraform Plan', icon: 'fa-diagram-project' },
  GITHUB_ACTIONS_GENERATION: { label: 'GitHub Actions Generation', icon: 'fa-github', brand: true },
  REPOSITORY_INSTALLATION: { label: 'Repository Installation', icon: 'fa-code-branch' },
  WORKFLOW_MONITORING: { label: 'Workflow Monitoring', icon: 'fa-satellite-dish' },
  INFRASTRUCTURE_DESTROY: { label: 'Infrastructure Destroy', icon: 'fa-trash-can' },
  INFRASTRUCTURE_RECOVERY: { label: 'Infrastructure Recovery', icon: 'fa-kit-medical' },
  INFRASTRUCTURE_LIFECYCLE: { label: 'Infrastructure Lifecycle', icon: 'fa-server' },
};

/**
 * Resolve a workflow phase to {label, icon, brand}. Prefers the canonical
 * backend phase names, then the roadmap keys (getPhaseMeta), then a generic
 * fallback — so it is a safe superset replacement for getPhaseMeta on the
 * Workflows page.
 */
export function getWorkflowPhaseMeta(key) {
  if (!key) return { label: 'Not started', icon: 'fa-circle-nodes', brand: false };
  return BACKEND_WORKFLOW_PHASE_META[key] || getPhaseMeta(key);
}

/**
 * Map a backend phase key to the workflow VIEW the resume router should render.
 * Data-driven on purpose: when a future phase becomes a real surface, only this
 * map + the WorkflowRunPage switch change — no hardcoded phase logic elsewhere.
 *
 * Today only `analysis` is a real, integrated surface; the rest resolve to
 * their (not-yet-integrated) view id so the resume router can show an honest
 * "this phase isn't available yet" state instead of guessing.
 */
export const WORKFLOW_PHASE_VIEW = {
  ANALYSIS: 'analysis',
  ARCHITECTURE_DECISION: 'planning',
  // Once a plan is selected the architecture decision is done; the active phase
  // becomes Docker Generation (Analysis → Architecture → Docker → Terraform), so
  // a selected/resumed run lands on the Docker surface to generate + review.
  PLAN_SELECTED: 'docker',
  DOCKER: 'docker',
  DOCKER_BUILD: 'docker',
  TERRAFORM_GENERATION: 'terraform',
  TERRAFORM_VALIDATION: 'terraform',
  TERRAFORM_PLAN: 'terraform',
  // Deployment orchestration — the final generation phase (Analysis →
  // Architecture → Docker → Terraform → GitHub Actions). A resumed run that has
  // reached (or completed) this phase lands on the GitHub Actions surface.
  GITHUB_ACTIONS_GENERATION: 'github_actions',
  // Repository installation — commit the generated pipelines onto a dedicated
  // branch of the user's repo (+ optional PR).
  REPOSITORY_INSTALLATION: 'repository_installation',
  // Workflow monitoring — the terminal phase: READ-ONLY observation of the
  // installed pipelines' GitHub Actions runs (Generate → Install → Monitor).
  WORKFLOW_MONITORING: 'monitoring',
  // Infrastructure destroy — tear down the provisioned AWS resources via a
  // GitHub Actions destroy.yml (the backend never runs Terraform).
  INFRASTRUCTURE_DESTROY: 'destroy',
  // Infrastructure recovery — read-only diagnosis of a failed bootstrap
  // (classify the failure + recommend a recovery; no execution).
  INFRASTRUCTURE_RECOVERY: 'recovery',
  // Infrastructure lifecycle — the FINAL operational phase (after monitoring):
  // status, terraform state, inventory, recovery history, retry/destroy actions.
  INFRASTRUCTURE_LIFECYCLE: 'lifecycle',
};

/** Views that are fully integrated with live backend data today. */
export const IMPLEMENTED_WORKFLOW_VIEWS = new Set([
  'analysis', 'planning', 'docker', 'terraform', 'github_actions',
  'repository_installation', 'monitoring', 'destroy', 'recovery', 'lifecycle',
]);

/* ===========================================================================
   Workflow revision (regenerate a phase + invalidate downstream)

   Mirrors the backend WorkflowRevisionService (PHASE_DEPENDENTS,
   REGENERATABLE_PHASES, CANONICAL_PHASE_ORDER) so the UI can render the phase
   navigator, the Regenerate button, and the dependency warning WITHOUT an extra
   round-trip. The backend remains the authoritative source of truth on execute.
   Keep these in lock-step with
   backend/app/services/core/workflow_revision_service.py.
   ========================================================================= */

/** Canonical left-to-right lifecycle order for the phase navigator. */
export const CANONICAL_PHASE_ORDER = [
  'ANALYSIS',
  'ARCHITECTURE_DECISION',
  'PLAN_SELECTED',
  'DOCKER',
  'DOCKER_BUILD',
  'TERRAFORM_GENERATION',
  'TERRAFORM_VALIDATION',
  'TERRAFORM_PLAN',
  'GITHUB_ACTIONS_GENERATION',
  'REPOSITORY_INSTALLATION',
  'WORKFLOW_MONITORING',
  'INFRASTRUCTURE_DESTROY',
  'INFRASTRUCTURE_RECOVERY',
  'INFRASTRUCTURE_LIFECYCLE',
];

/** Direct dependency edges: phase → phases that CONSUME its output. */
export const PHASE_DEPENDENTS = {
  PLAN_SELECTED: ['DOCKER', 'TERRAFORM_GENERATION'],
  DOCKER: ['DOCKER_BUILD', 'GITHUB_ACTIONS_GENERATION'],
  TERRAFORM_GENERATION: ['TERRAFORM_VALIDATION', 'TERRAFORM_PLAN', 'GITHUB_ACTIONS_GENERATION'],
  TERRAFORM_VALIDATION: ['TERRAFORM_PLAN'],
  GITHUB_ACTIONS_GENERATION: ['REPOSITORY_INSTALLATION'],
  REPOSITORY_INSTALLATION: ['WORKFLOW_MONITORING'],
};

/** Phases a user may regenerate (the inline generation phases only). */
export const REGENERATABLE_PHASES = new Set([
  'DOCKER',
  'TERRAFORM_GENERATION',
  'GITHUB_ACTIONS_GENERATION',
]);

/**
 * Phases at which a workflow may be CANCELLED (the deployment/observation tail).
 * Mirrors the backend WorkflowCancellationService.CANCELLABLE_PHASES. Cancelling
 * stops any in-flight GitHub Actions run and marks the workflow cancelled while
 * preserving artifacts, so it can later resume from a previous phase.
 */
export const CANCELLABLE_PHASES = new Set([
  'GITHUB_ACTIONS_GENERATION',
  'REPOSITORY_INSTALLATION',
  'WORKFLOW_MONITORING',
]);

/** phases_state statuses that count as "done" (mirrors the backend set). */
export const DONE_PHASE_STATUSES = new Set([
  'completed',
  'completed_with_fallback',
  'completed_no_files',
]);

/** Status stamped on a phase whose upstream input was regenerated. */
export const INVALIDATED_STATUS = 'invalidated';

/**
 * Transitive closure of phases that depend on `phase`'s output, in canonical
 * order. Breadth-first over PHASE_DEPENDENTS; excludes `phase` itself.
 */
export function downstreamPhases(phase) {
  const seen = new Set();
  const queue = [...(PHASE_DEPENDENTS[phase] || [])];
  while (queue.length) {
    const next = queue.shift();
    if (seen.has(next)) continue;
    seen.add(next);
    queue.push(...(PHASE_DEPENDENTS[next] || []));
  }
  return CANONICAL_PHASE_ORDER.filter((p) => seen.has(p));
}

/** True when a phase entry's status means it produced output. */
export function isPhaseDone(status) {
  return DONE_PHASE_STATUSES.has(status);
}

/** A completed (or invalidated) regeneratable phase can be regenerated. */
export function canRegeneratePhase(phase, status) {
  return (
    REGENERATABLE_PHASES.has(phase) &&
    (DONE_PHASE_STATUSES.has(status) || status === INVALIDATED_STATUS)
  );
}

/**
 * Resolve a workflow's saved phase to its view id. A null/unknown phase means
 * the run hasn't advanced past intake → resume at Analysis (the first phase).
 */
export function resolveWorkflowView(currentPhase) {
  if (!currentPhase) return 'analysis';
  return WORKFLOW_PHASE_VIEW[currentPhase] || 'analysis';
}

/**
 * Status metadata — drives the StatusBadge / PhaseStatusBadge colors and icons.
 * `variant` maps to the badge-* classes defined in app.css.
 */
export const STATUS_META = {
  // Generic lifecycle
  completed: { label: 'Completed', variant: 'success', icon: 'fa-circle-check' },
  succeeded: { label: 'Succeeded', variant: 'success', icon: 'fa-circle-check' },
  passed: { label: 'Passed', variant: 'success', icon: 'fa-circle-check' },
  healthy: { label: 'Healthy', variant: 'success', icon: 'fa-heart-pulse' },
  active: { label: 'Active', variant: 'success', icon: 'fa-circle-play' },
  deployed: { label: 'Deployed', variant: 'success', icon: 'fa-circle-check' },
  approved: { label: 'Approved', variant: 'success', icon: 'fa-thumbs-up' },

  running: { label: 'Running', variant: 'running', icon: 'fa-spinner' },
  in_progress: { label: 'In Progress', variant: 'running', icon: 'fa-spinner' },
  building: { label: 'Building', variant: 'running', icon: 'fa-hammer' },
  provisioning: {
    label: 'Provisioning',
    variant: 'running',
    icon: 'fa-cloud-arrow-up',
  },

  pending: { label: 'Pending', variant: 'pending', icon: 'fa-clock' },
  queued: { label: 'Queued', variant: 'pending', icon: 'fa-clock' },
  not_started: { label: 'Not Started', variant: 'pending', icon: 'fa-minus' },
  draft: { label: 'Draft', variant: 'pending', icon: 'fa-pen-ruler' },

  degraded: {
    label: 'Degraded',
    variant: 'warning',
    icon: 'fa-triangle-exclamation',
  },
  warning: {
    label: 'Warning',
    variant: 'warning',
    icon: 'fa-triangle-exclamation',
  },
  human_review: {
    label: 'Needs Review',
    variant: 'warning',
    icon: 'fa-user-check',
  },
  // A phase whose upstream input was regenerated — its output is stale and it
  // must be re-run before anything downstream of it can proceed.
  invalidated: {
    label: 'Stale · re-run',
    variant: 'warning',
    icon: 'fa-rotate',
  },
  awaiting_approval: {
    label: 'Awaiting Approval',
    variant: 'warning',
    icon: 'fa-hourglass-half',
  },
  // Backend Workflow.status when a run pauses for user plan selection / input.
  awaiting_input: {
    label: 'Awaiting Input',
    variant: 'warning',
    icon: 'fa-hourglass-half',
  },

  failed: { label: 'Failed', variant: 'danger', icon: 'fa-circle-xmark' },
  error: { label: 'Error', variant: 'danger', icon: 'fa-circle-xmark' },
  blocked: { label: 'Blocked', variant: 'danger', icon: 'fa-ban' },

  // Infrastructure-destroy lifecycle (phases_state[INFRASTRUCTURE_DESTROY].status).
  destroy_requested: { label: 'Destroy requested', variant: 'warning', icon: 'fa-hourglass-half' },
  destroy_running: { label: 'Destroying', variant: 'running', icon: 'fa-spinner' },
  destroy_succeeded: { label: 'Destroyed', variant: 'success', icon: 'fa-circle-check' },
  destroy_failed: { label: 'Destroy failed', variant: 'danger', icon: 'fa-circle-xmark' },
  // Infrastructure-recovery diagnosis (phases_state[INFRASTRUCTURE_RECOVERY].status).
  recovery_available: { label: 'Recovery available', variant: 'warning', icon: 'fa-kit-medical' },
  no_failure_detected: { label: 'No failure detected', variant: 'success', icon: 'fa-circle-check' },
  // Infrastructure lifecycle — aggregate status + event statuses.
  Healthy: { label: 'Healthy', variant: 'success', icon: 'fa-circle-check' },
  Failed: { label: 'Failed', variant: 'danger', icon: 'fa-circle-xmark' },
  Destroyed: { label: 'Destroyed', variant: 'pending', icon: 'fa-ban' },
  Pending: { label: 'Pending', variant: 'pending', icon: 'fa-hourglass-half' },
  requested: { label: 'Requested', variant: 'warning', icon: 'fa-paper-plane' },
  info: { label: 'Info', variant: 'pending', icon: 'fa-circle-info' },
  suspended: { label: 'Suspended', variant: 'danger', icon: 'fa-user-slash' },
  // Backend terminal Workflow.status for an abandoned run.
  cancelled: { label: 'Cancelled', variant: 'pending', icon: 'fa-ban' },

  // Members / invitations / credentials
  invited: { label: 'Invited', variant: 'info', icon: 'fa-paper-plane' },
  accepted: { label: 'Accepted', variant: 'success', icon: 'fa-circle-check' },
  expired: { label: 'Expired', variant: 'pending', icon: 'fa-hourglass-end' },
  rejected: { label: 'Rejected', variant: 'danger', icon: 'fa-circle-xmark' },
  revoked: { label: 'Revoked', variant: 'danger', icon: 'fa-ban' },
  valid: { label: 'Valid', variant: 'success', icon: 'fa-shield-halved' },
  connected: { label: 'Connected', variant: 'success', icon: 'fa-plug-circle-check' },
  invalid: { label: 'Invalid', variant: 'danger', icon: 'fa-shield-virus' },
  not_configured: {
    label: 'Not Configured',
    variant: 'pending',
    icon: 'fa-circle-minus',
  },
};

/** Resolve status metadata, normalizing case/spacing, with a sane fallback. */
export function getStatusMeta(status) {
  if (!status) return { label: '—', variant: 'pending', icon: 'fa-minus' };
  const key = String(status).toLowerCase().replace(/[\s-]+/g, '_');
  return (
    STATUS_META[key] || {
      label: String(status),
      variant: 'info',
      icon: 'fa-circle-info',
    }
  );
}

/** Cloud provider display metadata. */
export const CLOUD_PROVIDERS = {
  aws: { label: 'AWS', icon: 'fa-aws', color: '#ff9900' },
  azure: { label: 'Azure', icon: 'fa-microsoft', color: '#3b82f6' },
  gcp: { label: 'Google Cloud', icon: 'fa-google', color: '#34a853' },
};

/** Artifact type display metadata. */
export const ARTIFACT_TYPES = {
  dockerfile: { label: 'Dockerfile', icon: 'fa-docker', brand: true },
  compose: { label: 'Docker Compose', icon: 'fa-layer-group' },
  terraform: { label: 'Terraform', icon: 'fa-cubes' },
  kubernetes: { label: 'Kubernetes', icon: 'fa-dharmachakra' },
  helm: { label: 'Helm Chart', icon: 'fa-ship' },
  cicd: { label: 'CI/CD Pipeline', icon: 'fa-code-branch' },
};

/* ===========================================================================
   Auth / workspace roles
   ========================================================================= */

export const ROLES = {
  ADMIN: 'ADMIN',
  DEVOPS_ENGINEER: 'DEVOPS_ENGINEER',
};

/** Role display metadata — drives <RoleBadge />. */
export const ROLE_META = {
  ADMIN: {
    label: 'Admin',
    short: 'Admin',
    icon: 'fa-crown',
    color: '#a78bfa',
    description: 'Owns the workspace, manages members, AWS & billing.',
  },
  DEVOPS_ENGINEER: {
    label: 'DevOps Engineer',
    short: 'Engineer',
    icon: 'fa-user-gear',
    color: '#60a5fa',
    description: 'Builds and ships infrastructure within the workspace.',
  },
};

export function getRoleMeta(role) {
  return (
    ROLE_META[role] || {
      label: role || 'Member',
      short: 'Member',
      icon: 'fa-user',
      color: 'var(--tx2)',
      description: '',
    }
  );
}

/* ===========================================================================
   Role-based sidebar navigation (Phase 8)
   ========================================================================= */

export const ROLE_NAV = {
  ADMIN: [
    {
      title: 'Platform',
      items: [
        { label: 'Dashboard', icon: 'fa-gauge-high', to: '/', end: true },
        { label: 'Projects', icon: 'fa-folder-tree', to: '/projects' },
        { label: 'Workflows', icon: 'fa-diagram-project', to: '/workflows' },
      ],
    },
    {
      title: 'Administration',
      items: [
        { label: 'Members', icon: 'fa-users', to: '/members' },
        { label: 'Invitations', icon: 'fa-paper-plane', to: '/invitations' },
        {
          label: 'AWS Credentials',
          icon: 'fa-aws',
          brand: true,
          to: '/aws-credentials',
        },
      ],
    },
    {
      title: 'Workspace',
      items: [{ label: 'Settings', icon: 'fa-gear', to: '/settings' }],
    },
  ],
  DEVOPS_ENGINEER: [
    {
      title: 'Platform',
      items: [
        { label: 'Dashboard', icon: 'fa-gauge-high', to: '/', end: true },
        { label: 'Projects', icon: 'fa-folder-tree', to: '/projects' },
        { label: 'Workflows', icon: 'fa-diagram-project', to: '/workflows' },
      ],
    },
    {
      title: 'Engineering',
      items: [
        { label: 'Artifacts', icon: 'fa-file-code', to: '/artifacts' },
        {
          label: 'Infrastructure',
          icon: 'fa-server',
          to: '/infrastructure',
          badge: 'IaC',
        },
      ],
    },
    {
      title: 'Workspace',
      items: [{ label: 'Settings', icon: 'fa-gear', to: '/settings' }],
    },
  ],
};

/** Resolve nav for a role, defaulting to the admin layout. */
export function getNavForRole(role) {
  return ROLE_NAV[role] || ROLE_NAV.ADMIN;
}

/* ===========================================================================
   AWS regions (for workspace setup + credentials dropdowns)
   ========================================================================= */

export const AWS_REGIONS = [
  { value: 'us-east-1', label: 'US East (N. Virginia) · us-east-1' },
  { value: 'us-east-2', label: 'US East (Ohio) · us-east-2' },
  { value: 'us-west-2', label: 'US West (Oregon) · us-west-2' },
  { value: 'eu-west-1', label: 'EU (Ireland) · eu-west-1' },
  { value: 'eu-west-3', label: 'EU (Paris) · eu-west-3' },
  { value: 'eu-central-1', label: 'EU (Frankfurt) · eu-central-1' },
  { value: 'ap-south-1', label: 'Asia Pacific (Mumbai) · ap-south-1' },
  { value: 'ap-southeast-1', label: 'Asia Pacific (Singapore) · ap-southeast-1' },
  { value: 'ap-northeast-1', label: 'Asia Pacific (Tokyo) · ap-northeast-1' },
];

/* ===========================================================================
   Workflow execution timeline (the live run experience, /workflows/*)

   This is the user-facing pipeline shown by <WorkflowTimeline /> at the top of
   every phase page. It is intentionally a *flat, ordered* list (distinct from
   the richer backend roadmap in WORKFLOW_PHASES above) so the timeline reads
   like a simple left-to-right journey. Each entry can map to a phase route;
   future phases reuse this same definition.
   ========================================================================= */

export const WORKFLOW_TIMELINE_PHASES = [
  { key: 'analysis', label: 'Analysis', icon: 'fa-magnifying-glass-chart', to: '/workflows/analysis' },
  { key: 'planning', label: 'Planning', icon: 'fa-clipboard-list', to: '/workflows/planning' },
  // Docker is a real, data-backed surface reached via /workflows/run/:id
  // (WorkflowDockerPhase) — never a standalone mock route. No `to` here so the
  // timeline shows the step but never links to a (removed) mock demo page.
  { key: 'docker', label: 'Docker', icon: 'fa-docker', brand: true },
  { key: 'terraform', label: 'Terraform', icon: 'fa-cubes', to: '/workflows/terraform' },
  // Terraform Validation is a real, data-backed sub-surface reached via
  // /workflows/run/:id (WorkflowTerraformPhase) — no standalone route, so no `to`.
  { key: 'terraform-validate', label: 'TF Validate', icon: 'fa-clipboard-check' },
  // Terraform Plan — the same data-backed sub-surface (WorkflowTerraformPhase),
  // shown after Validation. No standalone route, so no `to`.
  { key: 'terraform-plan', label: 'TF Plan', icon: 'fa-diagram-project' },
  { key: 'cicd', label: 'GitHub Actions', icon: 'fa-github', brand: true, to: '/workflows/cicd' },
  { key: 'execution', label: 'Execution Center', icon: 'fa-tower-broadcast', to: '/workflows/execution' },
  { key: 'infrastructure', label: 'Infrastructure Dashboard', icon: 'fa-server', to: '/workflows/infrastructure-dashboard' },
];

/** Index of a phase within the timeline (−1 if unknown). */
export function getTimelineIndex(key) {
  return WORKFLOW_TIMELINE_PHASES.findIndex((p) => p.key === key);
}

/**
 * Derive a {key: status} map for the timeline from the *current* phase, where
 * everything before it is completed, the current phase is running and the rest
 * are not started. Callers can pass `overrides` to pin specific phases (e.g.
 * mark the current phase completed or failed).
 */
export function deriveTimelineStatuses(currentKey, overrides = {}) {
  const currentIdx = getTimelineIndex(currentKey);
  const map = {};
  WORKFLOW_TIMELINE_PHASES.forEach((phase, idx) => {
    if (idx < currentIdx) map[phase.key] = 'completed';
    else if (idx === currentIdx) map[phase.key] = 'running';
    else map[phase.key] = 'not_started';
  });
  return { ...map, ...overrides };
}
