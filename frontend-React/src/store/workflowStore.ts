import { create } from 'zustand'
import type { TaskResponse, PlanPreviewResponse, LogEntry, ArchitectureDecision } from '@/types'
import type { WorkflowPhaseResponse } from '@/services/workflowApi'
import type { CorrectorStatusResponse } from '@/services/correctorApi'

// ── Step definitions ──────────────────────────────────────────────────────────

export type WorkflowStep =
  | 'INPUT'
  | 'ARCHITECTURE_DECISION'   // unified replacement for PLAN + COST_ESTIMATION
  | 'INFRA'
  | 'DOCKER_BUILD'
  | 'CORRECTOR_REVIEW'
  | 'TERRAFORM'
  | 'KUBERNETES'
  | 'SUMMARY'
  | 'CICD'
  | 'RESULT'

// Canonical step order — CORRECTOR_REVIEW sits between DOCKER_BUILD and TERRAFORM.
// It is conditionally rendered in the sidebar (only when a failure/review phase
// is active) but always present here so goToStep() and progress work correctly.
export const WORKFLOW_STEPS: WorkflowStep[] = [
  'INPUT',
  'ARCHITECTURE_DECISION',
  'INFRA',
  'DOCKER_BUILD',
  'CORRECTOR_REVIEW',
  'TERRAFORM',
  'KUBERNETES',
  'CICD',
  'SUMMARY',
  'RESULT',
]

export const STEP_META: Record<WorkflowStep, { label: string; description: string }> = {
  INPUT:                  { label: 'Project Input',           description: 'Define project requirements'                },
  ARCHITECTURE_DECISION:  { label: 'Architecture Decision',   description: 'Compare strategies & select deployment plan' },
  INFRA:                  { label: 'Infrastructure',          description: 'Docker & container configuration'            },
  DOCKER_BUILD:           { label: 'Docker Build',            description: 'Build & verify the Docker image'             },
  CORRECTOR_REVIEW:       { label: 'AI Remediation',          description: 'Review AI-suggested fixes for build failure' },
  TERRAFORM:              { label: 'Terraform',               description: 'Infrastructure as code (.tf files)'          },
  KUBERNETES:             { label: 'Kubernetes',              description: 'Container orchestration manifests'           },
  SUMMARY:                { label: 'Summary',                 description: 'Architecture overview'                       },
  CICD:                   { label: 'CI/CD Pipeline',          description: 'GitHub Actions workflows'                    },
  RESULT:                 { label: 'Final Output',            description: 'Logs, artifacts & download'                  },
}

// Phases that activate the CORRECTOR_REVIEW step
const CORRECTOR_ACTIVE_PHASES = new Set([
  'docker_build_failed',
  'corrector_analysis_running',
  'corrector_analysis_completed',
  'human_review_required',
  'execution_failed',
])

export function shouldShowCorrectorStep(currentPhase: string): boolean {
  return CORRECTOR_ACTIVE_PHASES.has(currentPhase)
}

export function hasExecutionFailed(currentPhase: string): boolean {
  return currentPhase === 'execution_failed'
}

export function canRetryBuild(retryCount: number, maxRetries: number): boolean {
  return retryCount < maxRetries
}

// ── State ─────────────────────────────────────────────────────────────────────

export interface WorkflowUserInput {
  prompt: string
  repo_url: string
  repository_visibility: 'public' | 'private'
  github_token: string
}

interface WorkflowStore {
  currentStep: WorkflowStep

  userInput: WorkflowUserInput
  envFile?: File

  // Architecture Decision phase state (replaces planPreview + requiresHumanValidation)
  architectureDecision?: ArchitectureDecision
  selectedPlanId?: string               // set after user clicks "Select This Plan"

  // Kept for legacy/backward-compat (old tasks that only have a single plan)
  planPreview?: PlanPreviewResponse
  requiresHumanValidation: boolean

  taskId?: string
  task?: TaskResponse

  // Step-by-step workflow: accumulated artifacts and phase state
  phaseArtifacts: Record<string, string>
  currentPhase: string
  isPhaseLoading: boolean

  // Locally-edited artifact content
  editedArtifacts: Record<string, string>

  // Corrector agent state
  correctorData?: CorrectorStatusResponse

  isLoading: boolean
  isGenerating: boolean
  error?: string
  logs: LogEntry[]

  // Actions
  goToStep: (step: WorkflowStep) => void
  setUserInput: (input: Partial<WorkflowUserInput>) => void
  setEnvFile: (file: File | undefined) => void
  setArchitectureDecision: (data: ArchitectureDecision) => void
  setSelectedPlanId: (id: string | undefined) => void
  setPlanPreview: (preview: PlanPreviewResponse) => void
  setTaskId: (id: string) => void
  setTask: (task: TaskResponse) => void
  mergePhaseResponse: (resp: WorkflowPhaseResponse) => void
  editArtifact: (key: string, content: string) => void
  setCorrectorData: (data: CorrectorStatusResponse) => void
  setLoading: (v: boolean) => void
  setPhaseLoading: (v: boolean) => void
  setGenerating: (v: boolean) => void
  setError: (err: string | undefined) => void
  clearError: () => void
  addLog: (log: LogEntry) => void
  reset: () => void
}

// ── Store factory ─────────────────────────────────────────────────────────────

const defaultUserInput: WorkflowUserInput = {
  prompt: '',
  repo_url: '',
  repository_visibility: 'public',
  github_token: '',
}

export const useWorkflowStore = create<WorkflowStore>((set) => ({
  currentStep: 'INPUT',
  userInput: defaultUserInput,
  requiresHumanValidation: false,
  editedArtifacts: {},
  phaseArtifacts: {},
  currentPhase: '',
  isLoading: false,
  isPhaseLoading: false,
  isGenerating: false,
  logs: [],

  goToStep: (currentStep) => set({ currentStep }),

  setUserInput: (input) =>
    set((s) => ({ userInput: { ...s.userInput, ...input } })),

  setEnvFile: (envFile) => set({ envFile }),

  setArchitectureDecision: (architectureDecision) => set({ architectureDecision }),

  setSelectedPlanId: (selectedPlanId) => set({ selectedPlanId }),

  setPlanPreview: (planPreview) =>
    set({
      planPreview,
      taskId: planPreview.task_id,
      requiresHumanValidation: planPreview.requires_user_input ?? false,
    }),

  setTaskId: (taskId) => set({ taskId }),

  setTask: (task) => set({ task }),

  mergePhaseResponse: (resp) =>
    set((s) => ({
      taskId: resp.task_id || s.taskId,
      currentPhase: resp.current_phase,
      phaseArtifacts: { ...s.phaseArtifacts, ...resp.artifacts },
      // Preserve architecture_decision if the response contains one
      ...(resp.architecture_decision ? { architectureDecision: resp.architecture_decision } : {}),
      logs: [
        ...s.logs,
        ...(resp.logs as LogEntry[]).filter(
          (l) => !s.logs.some((e) => e.message === l.message),
        ),
      ],
    })),

  editArtifact: (key, content) =>
    set((s) => ({ editedArtifacts: { ...s.editedArtifacts, [key]: content } })),

  setCorrectorData: (correctorData) => set({ correctorData }),

  setLoading: (isLoading) => set({ isLoading }),

  setPhaseLoading: (isPhaseLoading) => set({ isPhaseLoading }),

  setGenerating: (isGenerating) => set({ isGenerating }),

  setError: (error) => set({ error }),

  clearError: () => set({ error: undefined }),

  addLog: (log) => set((s) => ({ logs: [...s.logs, log] })),

  reset: () =>
    set({
      currentStep: 'INPUT',
      userInput: defaultUserInput,
      envFile: undefined,
      architectureDecision: undefined,
      selectedPlanId: undefined,
      planPreview: undefined,
      requiresHumanValidation: false,
      taskId: undefined,
      task: undefined,
      editedArtifacts: {},
      phaseArtifacts: {},
      currentPhase: '',
      correctorData: undefined,
      isLoading: false,
      isPhaseLoading: false,
      isGenerating: false,
      error: undefined,
      logs: [],
    }),
}))
