import { useCallback, useEffect, useRef } from 'react'
import { Loader2, RotateCcw, AlertCircle, X } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

import { StepperSidebar }             from '@/components/workflow/StepperSidebar'
import { InputStep }                   from '@/steps/InputStep'
import { ArchitectureDecisionStep }    from '@/steps/ArchitectureDecisionStep'
import { InfraStep }                   from '@/steps/InfraStep'
import { DockerBuildStep }             from '@/steps/DockerBuildStep'
import { CorrectorReviewStep }         from '@/steps/CorrectorReviewStep'
import { TerraformStep }               from '@/steps/TerraformStep'
import { KubernetesStep }              from '@/steps/KubernetesStep'
import { SummaryStep }                 from '@/steps/SummaryStep'
import { CicdStep }                    from '@/steps/CicdStep'
import { ResultStep }                  from '@/steps/ResultStep'

import { useWorkflowStore, useWorkflowStore as _store } from '@/store/workflowStore'
import { shouldShowCorrectorStep }                       from '@/store/workflowStore'
import type { WorkflowStep } from '@/store/workflowStore'
import {
  workflowArchitectureDecision,
  workflowSelectPlan,
  workflowRunDocker,
  workflowRunTerraform,
  workflowRunKubernetes,
  workflowRunCicd,
  workflowGetState,
  pollTask,
} from '@/services/workflowApi'
import { getCorrectorAnalysis } from '@/services/correctorApi'
import { TASKS_KEY }        from '@/hooks/useTasks'
import { isTerminalStatus } from '@/lib/utils'
import { cn }               from '@/lib/utils'

const SESSION_KEY = 'wf_task_id'

// Backend phase → UI step (used when restoring state on page refresh).
const PHASE_TO_STEP: Record<string, WorkflowStep> = {
  architecture_decision_complete: 'ARCHITECTURE_DECISION',
  planning_complete:              'ARCHITECTURE_DECISION',   // legacy compat
  docker_completed:               'INFRA',
  docker_build_running:           'DOCKER_BUILD',
  docker_build_success:           'DOCKER_BUILD',
  docker_build_failed:            'DOCKER_BUILD',
  corrector_analysis_running:     'CORRECTOR_REVIEW',
  human_review_required:          'CORRECTOR_REVIEW',
  execution_failed:               'CORRECTOR_REVIEW',
  terraform_completed:            'TERRAFORM',
  kubernetes_completed:           'KUBERNETES',
  completed:                      'CICD',
}

const STEP_TO_EXPECTED_PHASE: Partial<Record<WorkflowStep, string>> = {
  ARCHITECTURE_DECISION: 'planning_complete',
  INFRA:                 'docker_completed',
  DOCKER_BUILD:          'docker_build_success',
  CORRECTOR_REVIEW:      'human_review_required',
  TERRAFORM:             'terraform_completed',
  KUBERNETES:            'kubernetes_completed',
}

// ── Debug panel ───────────────────────────────────────────────────────────────

function DebugPanel({ currentStep, currentPhase, lastApiCall }: {
  currentStep: string; currentPhase: string; lastApiCall: string
}) {
  return (
    <div style={{
      position: 'fixed', bottom: 100, right: 16, zIndex: 9999,
      padding: '10px 14px', borderRadius: 8,
      background: 'rgba(0,0,0,0.88)', color: '#4ade80',
      fontFamily: 'monospace', fontSize: 11, lineHeight: 1.7,
      border: '1px solid rgba(74,222,128,0.35)', minWidth: 220,
    }}>
      <div style={{ fontWeight: 700, marginBottom: 4, color: '#86efac', letterSpacing: '0.05em' }}>⬛ WORKFLOW DEBUG</div>
      <div>Step:&nbsp;&nbsp;&nbsp;<span style={{ color: '#fff' }}>{currentStep || '—'}</span></div>
      <div>Phase:&nbsp;&nbsp;<span style={{ color: '#fbbf24' }}>{currentPhase || '—'}</span></div>
      <div>Last&nbsp;API:&nbsp;<span style={{ color: '#38bdf8' }}>{lastApiCall || '—'}</span></div>
    </div>
  )
}

// ── Generating overlay ────────────────────────────────────────────────────────

function GeneratingOverlay({ taskId, label }: { taskId?: string; label?: string }) {
  const STAGES = [
    { label: 'Architecture analysis',   color: 'bg-purple-500' },
    { label: 'Cost estimation',         color: 'bg-emerald-500' },
    { label: 'Infrastructure gen.',     color: 'bg-cyan-500'   },
    { label: 'Terraform & Kubernetes',  color: 'bg-orange-500' },
    { label: 'CI/CD pipeline',          color: 'bg-brand-500'  },
  ]
  return (
    <div className={cn(
      'absolute inset-0 z-20 flex items-center justify-center',
      'bg-white/90 dark:bg-surface-900/90 backdrop-blur-sm',
    )}>
      <div className="w-full max-w-md px-6 space-y-6">
        <div className={cn(
          'flex items-center gap-4 p-4 rounded-xl',
          'bg-brand-50 dark:bg-brand-600/10',
          'border border-brand-200 dark:border-brand-500/20',
        )}>
          <Loader2 className="w-5 h-5 text-brand-500 animate-spin shrink-0" />
          <div>
            <p className="text-sm font-semibold text-brand-700 dark:text-brand-300">
              {label ?? 'AI agents are working…'}
            </p>
            <p className="text-xs text-brand-600/60 dark:text-brand-400/60 mt-0.5">
              30–90 seconds per phase.
            </p>
          </div>
        </div>
        <div className="space-y-3">
          {STAGES.map(({ label: l, color }) => (
            <div key={l}>
              <div className="flex items-center justify-between text-xs text-slate-400 dark:text-slate-500 mb-1">
                <span>{l}</span>
                <Loader2 className="w-3 h-3 animate-spin" />
              </div>
              <div className="h-1 rounded-full bg-slate-200 dark:bg-surface-700">
                <div className={`h-1 rounded-full ${color} opacity-60 animate-pulse`} style={{ width: '65%' }} />
              </div>
            </div>
          ))}
        </div>
        {taskId && (
          <p className="text-[10px] text-slate-400 dark:text-slate-600 text-center font-mono">
            task: {taskId}
          </p>
        )}
      </div>
    </div>
  )
}

// ── Error banner ──────────────────────────────────────────────────────────────

function ErrorBanner({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div className={cn(
      'flex items-start gap-3 px-4 py-3 mx-4 mt-3 rounded-xl',
      'bg-red-50 dark:bg-red-500/10',
      'border border-red-200 dark:border-red-500/20',
    )}>
      <AlertCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
      <p className="flex-1 text-sm text-red-700 dark:text-red-300">{message}</p>
      <button onClick={onDismiss} className="shrink-0 p-0.5 rounded text-red-400 hover:text-red-600 transition-colors">
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}

// ── Legacy polling hook ───────────────────────────────────────────────────────

function useGenerationPolling() {
  const { taskId, isGenerating, setTask, setGenerating, setError, addLog } = useWorkflowStore()
  const qc = useQueryClient()
  const stoppedRef = useRef(false)
  const timerRef   = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!isGenerating || !taskId) return
    stoppedRef.current = false

    async function poll() {
      if (stoppedRef.current) return
      try {
        const task = await pollTask(taskId!)
        qc.setQueryData([...TASKS_KEY, taskId], task)
        qc.invalidateQueries({ queryKey: TASKS_KEY })
        if (task.logs?.length) task.logs.forEach((l) => addLog(l))
        if (isTerminalStatus(task.status) || task.status === 'awaiting_human_review') {
          stoppedRef.current = true
          if (task.status === 'failed') setError(task.error_message ?? 'Generation failed.')
          else setTask(task)
          setGenerating(false)
          return
        }
      } catch { /* network hiccup */ }
      timerRef.current = setTimeout(poll, 3_000)
    }

    poll()
    return () => {
      stoppedRef.current = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isGenerating, taskId])
}

// ── Corrector polling hook ────────────────────────────────────────────────────

function useCorrectorPolling() {
  const { taskId, currentStep, currentPhase, goToStep, setCorrectorData, mergePhaseResponse } = useWorkflowStore()
  const stoppedRef = useRef(false)
  const timerRef   = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (currentStep !== 'DOCKER_BUILD') return
    if (currentPhase !== 'docker_build_failed') return
    if (!taskId) return
    stoppedRef.current = false

    async function poll() {
      if (stoppedRef.current) return
      try {
        const data = await getCorrectorAnalysis(taskId!)
        setCorrectorData(data)
        const phase = data.current_phase
        if (phase === 'human_review_required' || phase === 'execution_failed') {
          stoppedRef.current = true
          mergePhaseResponse({ task_id: taskId!, current_phase: phase, status: 'in_progress', artifacts: {}, terraform_outputs: {}, logs: [], message: '' })
          goToStep('CORRECTOR_REVIEW')
          return
        }
      } catch { /* ignore */ }
      if (!stoppedRef.current) timerRef.current = setTimeout(poll, 3_000)
    }

    timerRef.current = setTimeout(poll, 2_000)
    return () => {
      stoppedRef.current = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, currentStep, currentPhase])
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WorkflowPage() {
  const {
    currentStep, currentPhase, userInput, envFile,
    isLoading, isGenerating, isPhaseLoading, error, taskId,
    setLoading, setPhaseLoading, setGenerating,
    setError, clearError, goToStep,
    setArchitectureDecision, setSelectedPlanId,
    setTaskId, setTask, mergePhaseResponse, reset,
  } = useWorkflowStore()

  useGenerationPolling()
  useCorrectorPolling()

  const overlayLabelRef = useRef<string>('')
  const lastApiCallRef  = useRef<string>('')

  // ── Session persistence ───────────────────────────────────────────────────
  useEffect(() => {
    if (taskId) sessionStorage.setItem(SESSION_KEY, taskId)
  }, [taskId])

  useEffect(() => {
    const stored = sessionStorage.getItem(SESSION_KEY)
    if (!stored || _store.getState().taskId) return
    Promise.all([workflowGetState(stored), pollTask(stored)])
      .then(([phaseResp, restoredTask]) => {
        const s = _store.getState()
        // mergePhaseResponse first so phaseArtifacts is populated before setTask enriches infra
        s.mergePhaseResponse(phaseResp)
        console.log('[InfrastructureFetch] session restore — phase:', phaseResp.current_phase, '| artifact keys:', Object.keys(phaseResp.artifacts ?? {}))
        console.log('[InfrastructureFetch] session restore — pollTask infra?.artifacts keys:', Object.keys(restoredTask.infra?.artifacts ?? {}))
        s.setTaskId(phaseResp.task_id)
        s.setTask(restoredTask)
        if (phaseResp.architecture_decision) s.setArchitectureDecision(phaseResp.architecture_decision)
        const step = PHASE_TO_STEP[phaseResp.current_phase]
        if (step) s.goToStep(step)
      })
      .catch(() => sessionStorage.removeItem(SESSION_KEY))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Step 1: Submit → Architecture Decision ────────────────────────────────
  const handleArchitectureDecision = useCallback(async (file: File) => {
    clearError()
    setLoading(true)
    overlayLabelRef.current = 'AI architect is analysing your project & generating strategies…'
    lastApiCallRef.current = 'architecture-decision'
    try {
      const resp = await workflowArchitectureDecision(
        {
          prompt:                userInput.prompt,
          repo_url:              userInput.repo_url,
          repository_visibility: userInput.repository_visibility,
          github_token:          userInput.github_token || undefined,
        },
        file,
      )
      mergePhaseResponse(resp)
      if (resp.architecture_decision) setArchitectureDecision(resp.architecture_decision)
      const task = await pollTask(resp.task_id)
      setTask(task)
      setTaskId(resp.task_id)
      goToStep('ARCHITECTURE_DECISION')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [userInput, clearError, setLoading, setArchitectureDecision, setTaskId, setTask, goToStep, setError, mergePhaseResponse])

  // ── Step 2a: Select a plan ────────────────────────────────────────────────
  const handleSelectPlan = useCallback(async (planId: string) => {
    if (!taskId) { setError('No task ID. Re-run architecture analysis.'); return }
    clearError()
    lastApiCallRef.current = 'select-plan'
    try {
      const resp = await workflowSelectPlan(taskId, planId)
      mergePhaseResponse(resp)
      setSelectedPlanId(planId)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [taskId, clearError, setSelectedPlanId, mergePhaseResponse, setError])

  // ── Step 2b: Confirm → run-docker → INFRA ────────────────────────────────
  const handleConfirmAndGenerate = useCallback(async () => {
    if (!taskId) return
    const state = _store.getState()
    // Guard: need planning_complete (set by /select-plan or legacy tasks)
    const validPhases = ['planning_complete', 'architecture_decision_complete']
    if (!validPhases.includes(state.currentPhase)) {
      setError('Select a deployment strategy before generating infrastructure.')
      return
    }
    clearError()
    setPhaseLoading(true)
    overlayLabelRef.current = 'Generating Docker & infrastructure artifacts…'
    lastApiCallRef.current = 'run-docker'
    try {
      const resp = await workflowRunDocker(taskId)
      console.log('[ArtifactHydration] run-docker response artifact keys:', Object.keys(resp.artifacts ?? {}))
      mergePhaseResponse(resp)
      const fresh = await workflowGetState(taskId)
      console.log('[ArtifactHydration] workflow-state artifact keys:', Object.keys(fresh.artifacts ?? {}), '| phase:', fresh.current_phase)
      mergePhaseResponse(fresh)
      const task = await pollTask(taskId)
      console.log('[ArtifactHydration] pollTask infra?.artifacts keys:', Object.keys(task.infra?.artifacts ?? {}))
      console.log('[ArtifactHydration] pollTask result?.infrastructure?.artifacts keys:', Object.keys((task.result?.infrastructure as { artifacts?: Record<string, string> })?.artifacts ?? {}))
      setTask(task)
      const nextStep = PHASE_TO_STEP[fresh.current_phase]
      console.log('[ArtifactHydration] navigating to step:', nextStep ?? 'INFRA', '(phase:', fresh.current_phase, ')')
      if (nextStep) goToStep(nextStep)
      else goToStep('INFRA')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPhaseLoading(false)
    }
  }, [taskId, clearError, setPhaseLoading, mergePhaseResponse, setTask, goToStep, setError])

  // ── Step 3: INFRA approved → Docker build ───────────────────────────────
  const handleApproveInfra = useCallback(async () => {
    if (!taskId) return
    if (_store.getState().currentPhase !== STEP_TO_EXPECTED_PHASE['INFRA']!) {
      setError('Infrastructure must be generated first'); return
    }
    clearError()
    goToStep('DOCKER_BUILD')
  }, [taskId, clearError, goToStep, setError])

  // ── Step 4: Docker succeeded → Terraform ────────────────────────────────
  const handleDockerBuildContinue = useCallback(async () => {
    if (!taskId) return
    if (_store.getState().currentPhase !== STEP_TO_EXPECTED_PHASE['DOCKER_BUILD']!) {
      setError('Docker build must succeed before running Terraform'); return
    }
    clearError()
    setPhaseLoading(true)
    overlayLabelRef.current = 'Generating Terraform files…'
    lastApiCallRef.current = 'run-terraform'
    try {
      const resp = await workflowRunTerraform(taskId)
      mergePhaseResponse(resp)
      const fresh = await workflowGetState(taskId)
      mergePhaseResponse(fresh)
      const task = await pollTask(taskId)
      setTask(task)
      const nextStep = PHASE_TO_STEP[fresh.current_phase]
      if (nextStep) goToStep(nextStep)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPhaseLoading(false)
    }
  }, [taskId, clearError, setPhaseLoading, mergePhaseResponse, setTask, goToStep, setError])

  // ── Corrector retry ───────────────────────────────────────────────────────
  const handleCorrectorRetry = useCallback(() => {
    clearError(); goToStep('DOCKER_BUILD')
  }, [clearError, goToStep])

  // ── Step 5: Terraform approved → Kubernetes ─────────────────────────────
  const handleApproveTerraform = useCallback(async () => {
    if (!taskId) return
    if (_store.getState().currentPhase !== STEP_TO_EXPECTED_PHASE['TERRAFORM']!) {
      setError('Invalid workflow order'); return
    }
    clearError()
    setPhaseLoading(true)
    overlayLabelRef.current = 'Generating Kubernetes manifests…'
    lastApiCallRef.current = 'run-kubernetes'
    try {
      const resp = await workflowRunKubernetes(taskId)
      mergePhaseResponse(resp)
      const fresh = await workflowGetState(taskId)
      mergePhaseResponse(fresh)
      const task = await pollTask(taskId)
      setTask(task)
      const nextStep = PHASE_TO_STEP[fresh.current_phase]
      if (nextStep) goToStep(nextStep)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPhaseLoading(false)
    }
  }, [taskId, clearError, setPhaseLoading, mergePhaseResponse, setTask, goToStep, setError])

  // ── Step 6: Kubernetes approved → CI/CD ─────────────────────────────────
  const handleApproveKubernetes = useCallback(async () => {
    if (!taskId) return
    if (_store.getState().currentPhase !== STEP_TO_EXPECTED_PHASE['KUBERNETES']!) {
      setError('Invalid workflow order'); return
    }
    clearError()
    setPhaseLoading(true)
    overlayLabelRef.current = 'Running CI/CD & finalizing…'
    lastApiCallRef.current = 'run-cicd'
    try {
      const resp = await workflowRunCicd(taskId)
      mergePhaseResponse(resp)
      const fresh = await workflowGetState(taskId)
      mergePhaseResponse(fresh)
      const task = await pollTask(taskId)
      setTask(task)
      const nextStep = PHASE_TO_STEP[fresh.current_phase]
      if (nextStep) goToStep(nextStep)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPhaseLoading(false)
    }
  }, [taskId, clearError, setPhaseLoading, mergePhaseResponse, setTask, goToStep, setError])

  const handleReset = useCallback(() => {
    sessionStorage.removeItem(SESSION_KEY)
    reset()
  }, [reset])

  const showOverlay = isGenerating || isPhaseLoading
  const correctorPhaseActive = shouldShowCorrectorStep(currentPhase)

  // ── Step routing ──────────────────────────────────────────────────────────
  const stepContent = {
    INPUT: (
      <InputStep onSubmit={handleArchitectureDecision} isLoading={isLoading} />
    ),
    ARCHITECTURE_DECISION: (
      <ArchitectureDecisionStep
        onSelectPlan={handleSelectPlan}
        onConfirm={handleConfirmAndGenerate}
        onBack={() => goToStep('INPUT')}
        isLoading={isLoading || isPhaseLoading}
        isGenerating={isPhaseLoading}
      />
    ),
    INFRA: (
      <InfraStep
        onApprove={handleApproveInfra}
        onBack={() => goToStep('ARCHITECTURE_DECISION')}
        isPhaseLoading={isPhaseLoading}
      />
    ),
    DOCKER_BUILD: (
      <DockerBuildStep
        onContinue={handleDockerBuildContinue}
        onBack={() => goToStep('INFRA')}
        isPhaseLoading={isPhaseLoading}
      />
    ),
    CORRECTOR_REVIEW: (
      <CorrectorReviewStep
        onRetryBuild={handleCorrectorRetry}
        onBackToInfra={() => goToStep('INFRA')}
        onStopWorkflow={handleReset}
      />
    ),
    TERRAFORM: (
      <TerraformStep
        onApprove={handleApproveTerraform}
        onBack={() => {
          if (correctorPhaseActive) goToStep('CORRECTOR_REVIEW')
          else goToStep('DOCKER_BUILD')
        }}
        isPhaseLoading={isPhaseLoading}
      />
    ),
    KUBERNETES: (
      <KubernetesStep
        onApprove={handleApproveKubernetes}
        onBack={() => goToStep('TERRAFORM')}
        isPhaseLoading={isPhaseLoading}
      />
    ),
    CICD: (
      <CicdStep
        onApprove={() => goToStep('SUMMARY')}
        onBack={() => goToStep('KUBERNETES')}
        isLoading={isPhaseLoading}
      />
    ),
    SUMMARY: (
      <SummaryStep onApprove={() => goToStep('RESULT')} onBack={() => goToStep('CICD')} />
    ),
    RESULT: <ResultStep onReset={handleReset} />,
  }[currentStep]

  return (
    <div className="flex h-full bg-slate-50/50 dark:bg-transparent">
      <StepperSidebar />

      <div className="flex-1 flex flex-col min-h-0 min-w-0 relative">
        <div className={cn(
          'shrink-0 flex items-center justify-between px-6 py-3',
          'border-b border-slate-200 dark:border-white/[0.06]',
          'bg-white dark:bg-surface-900',
        )}>
          <div>
            <h1 className="text-base font-semibold text-slate-900 dark:text-white leading-tight">
              AI DevSecOps Workflow
            </h1>
            <p className="text-xs text-slate-400 dark:text-slate-600 mt-0.5">
              Senior cloud architect assistant — sequential, validated pipeline
            </p>
          </div>
          {currentStep !== 'INPUT' && (
            <button
              onClick={handleReset}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                'border border-slate-200 dark:border-white/[0.06]',
                'text-slate-400 dark:text-slate-500',
                'hover:text-slate-700 dark:hover:text-slate-300',
                'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
              )}
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Start over
            </button>
          )}
        </div>

        {error && <ErrorBanner message={error} onDismiss={clearError} />}

        <div className="flex-1 min-h-0 relative">
          {showOverlay && (
            <GeneratingOverlay taskId={taskId} label={overlayLabelRef.current} />
          )}
          {stepContent}
        </div>
      </div>

      <DebugPanel
        currentStep={currentStep}
        currentPhase={currentPhase}
        lastApiCall={lastApiCallRef.current}
      />
    </div>
  )
}
