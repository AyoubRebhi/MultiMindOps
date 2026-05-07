import { create } from 'zustand'
import type { TaskResponse, PlanPreviewResponse, LogEntry } from '@/types'
import type { WorkflowPhaseResponse } from '@/services/workflowApi'

// ── Step definitions ──────────────────────────────────────────────────────────

export type WorkflowStep =
  | 'INPUT'
  | 'PLAN'
  | 'INFRA'
  | 'DOCKER_BUILD'
  | 'TERRAFORM'
  | 'KUBERNETES'
  | 'SUMMARY'
  | 'CICD'
  | 'RESULT'

export const WORKFLOW_STEPS: WorkflowStep[] = [
  'INPUT', 'PLAN', 'INFRA', 'DOCKER_BUILD', 'TERRAFORM', 'KUBERNETES', 'CICD', 'SUMMARY', 'RESULT',
]

export const STEP_META: Record<WorkflowStep, { label: string; description: string }> = {
  INPUT:        { label: 'Project Input',    description: 'Define project requirements'             },
  PLAN:         { label: 'Plan Review',      description: 'Approve the AI-generated plan'           },
  INFRA:        { label: 'Infrastructure',   description: 'Docker & container configuration'        },
  DOCKER_BUILD: { label: 'Docker Build',     description: 'Build & verify the Docker image'         },
  TERRAFORM:    { label: 'Terraform',        description: 'Infrastructure as code (.tf files)'      },
  KUBERNETES:   { label: 'Kubernetes',       description: 'Container orchestration manifests'       },
  SUMMARY:      { label: 'Summary',          description: 'Architecture overview'                   },
  CICD:         { label: 'CI/CD Pipeline',   description: 'GitHub Actions workflows'                },
  RESULT:       { label: 'Final Output',     description: 'Logs, artifacts & download'              },
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

  planPreview?: PlanPreviewResponse
  requiresHumanValidation: boolean

  taskId?: string
  task?: TaskResponse

  // Step-by-step workflow: accumulated artifacts and phase state
  phaseArtifacts: Record<string, string>
  currentPhase: string
  isPhaseLoading: boolean

  // Locally-edited artifact content — key matches artifact record key
  editedArtifacts: Record<string, string>

  isLoading: boolean
  isGenerating: boolean
  error?: string
  logs: LogEntry[]

  // Actions
  goToStep: (step: WorkflowStep) => void
  setUserInput: (input: Partial<WorkflowUserInput>) => void
  setEnvFile: (file: File | undefined) => void
  setPlanPreview: (preview: PlanPreviewResponse) => void
  setTaskId: (id: string) => void
  setTask: (task: TaskResponse) => void
  mergePhaseResponse: (resp: WorkflowPhaseResponse) => void
  editArtifact: (key: string, content: string) => void
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
      logs: [
        ...s.logs,
        ...(resp.logs as LogEntry[]).filter(
          (l) => !s.logs.some((e) => e.message === l.message),
        ),
      ],
    })),

  editArtifact: (key, content) =>
    set((s) => ({ editedArtifacts: { ...s.editedArtifacts, [key]: content } })),

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
      planPreview: undefined,
      requiresHumanValidation: false,
      taskId: undefined,
      task: undefined,
      editedArtifacts: {},
      phaseArtifacts: {},
      currentPhase: '',
      isLoading: false,
      isPhaseLoading: false,
      isGenerating: false,
      error: undefined,
      logs: [],
    }),
}))
