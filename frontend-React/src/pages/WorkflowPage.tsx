import { useCallback, useEffect, useRef } from 'react'
import { Loader2, RotateCcw, AlertCircle, X } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

import { StepperSidebar }       from '@/components/workflow/StepperSidebar'
import { InputStep }             from '@/steps/InputStep'
import { PlanStep }              from '@/steps/PlanStep'
import { InfraStep }             from '@/steps/InfraStep'
import { CostEstimationStep }    from '@/steps/CostEstimationStep'
import { DockerBuildStep }       from '@/steps/DockerBuildStep'
import { TerraformStep }         from '@/steps/TerraformStep'
import { KubernetesStep }        from '@/steps/KubernetesStep'
import { SummaryStep }           from '@/steps/SummaryStep'
import { CicdStep }              from '@/steps/CicdStep'
import { ResultStep }            from '@/steps/ResultStep'

import { useWorkflowStore, useWorkflowStore as _store } from '@/store/workflowStore'
import type { WorkflowStep } from '@/store/workflowStore'
import {
  generateArtifacts,
  approvePlanHumanValidation,
  pollTask,
  workflowPlan,
  workflowRunDocker,
  workflowRunTerraform,
  workflowRunKubernetes,
  workflowRunCicd,
  workflowGetState,
} from '@/services/workflowApi'
import { TASKS_KEY } from '@/hooks/useTasks'
import { isTerminalStatus } from '@/lib/utils'
import { cn } from '@/lib/utils'
import type { PlanValidationDecision } from '@/types'

const SESSION_KEY = 'wf_task_id'

// Backend phase → UI step used when restoring state after page refresh.
// COST_ESTIMATION is a frontend-only step with no backend phase; page-refresh
// restores the nearest real phase instead.
const PHASE_TO_STEP: Record<string, WorkflowStep> = {
  planning_complete:      'PLAN',
  docker_completed:       'INFRA',       // user already saw cost estimation
  docker_build_running:   'DOCKER_BUILD',
  docker_build_success:   'DOCKER_BUILD',
  docker_build_failed:    'DOCKER_BUILD',
  terraform_completed:    'TERRAFORM',
  kubernetes_completed:   'KUBERNETES',
  completed:              'CICD',
}

// Expected backend phase that must be active before the step's API call fires.
const STEP_TO_EXPECTED_PHASE: Partial<Record<WorkflowStep, string>> = {
  PLAN:         'planning_complete',
  INFRA:        'docker_completed',
  DOCKER_BUILD: 'docker_build_success',
  TERRAFORM:    'terraform_completed',
  KUBERNETES:   'kubernetes_completed',
}

// ── Debug panel ───────────────────────────────────────────────────────────────

function DebugPanel({ currentStep, currentPhase, lastApiCall }: {
  currentStep: string; currentPhase: string; lastApiCall: string
}) {
  return (
    <div style={{
      position: 'fixed', bottom: 16, right: 16, zIndex: 9999,
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
    { label: 'Codebase analysis',      color: 'bg-purple-500' },
    { label: 'Infrastructure gen.',    color: 'bg-cyan-500'   },
    { label: 'Terraform & Kubernetes', color: 'bg-orange-500' },
    { label: 'CI/CD pipeline',         color: 'bg-brand-500'  },
    { label: 'Security scanning',      color: 'bg-rose-500'   },
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
          if (task.status === 'failed') {
            setError(task.error_message ?? 'Generation failed.')
          } else {
            setTask(task)
          }
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

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WorkflowPage() {
  const {
    currentStep,
    currentPhase,
    userInput,
    envFile,
    isLoading,
    isGenerating,
    isPhaseLoading,
    error,
    requiresHumanValidation,
    taskId,
    setLoading,
    setPhaseLoading,
    setGenerating,
    setError,
    clearError,
    goToStep,
    setPlanPreview,
    setTaskId,
    setTask,
    mergePhaseResponse,
    reset,
  } = useWorkflowStore()

  useGenerationPolling()

  const rejectedMsgRef  = useRef<string | null>(null)
  const overlayLabelRef = useRef<string>('')
  const lastApiCallRef  = useRef<string>('')

  // ── Persist taskId across page refreshes ─────────────────────────────────
  useEffect(() => {
    if (taskId) sessionStorage.setItem(SESSION_KEY, taskId)
  }, [taskId])

  // ── Restore workflow state on page load ───────────────────────────────────
  useEffect(() => {
    const stored = sessionStorage.getItem(SESSION_KEY)
    if (!stored || _store.getState().taskId) return

    Promise.all([workflowGetState(stored), pollTask(stored)])
      .then(([phaseResp, restoredTask]) => {
        const s = _store.getState()
        s.mergePhaseResponse(phaseResp)
        s.setTaskId(phaseResp.task_id)
        s.setTask(restoredTask)
        const step = PHASE_TO_STEP[phaseResp.current_phase]
        if (step) s.goToStep(step)
      })
      .catch(() => sessionStorage.removeItem(SESSION_KEY))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Step 1: Submit → plan ─────────────────────────────────────────────────
  const handlePlanPreview = useCallback(async (file: File) => {
    clearError()
    setLoading(true)
    overlayLabelRef.current = 'Running AI planning…'
    try {
      const resp = await workflowPlan(
        {
          prompt:                userInput.prompt,
          repo_url:              userInput.repo_url,
          repository_visibility: userInput.repository_visibility,
          github_token:          userInput.github_token || undefined,
        },
        file,
      )
      mergePhaseResponse(resp)
      setPlanPreview({
        task_id:             resp.task_id,
        status:              resp.status,
        requires_user_input: true,
        plan:                resp.logs as unknown as undefined,
        logs:                resp.logs as never[],
      })
      const task = await pollTask(resp.task_id)
      setTask(task)
      if (task.plan) {
        setPlanPreview({
          task_id:             resp.task_id,
          status:              resp.status,
          requires_user_input: true,
          plan:                task.plan,
          logs:                (task.logs ?? []) as never[],
        })
      }
      goToStep('PLAN')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [userInput, clearError, setLoading, setPlanPreview, goToStep, setError, mergePhaseResponse, setTask])

  // ── Step 2a: Standard (legacy) path ──────────────────────────────────────
  const handleApproveStandard = useCallback(async (approvedArtifacts: string[]) => {
    clearError()
    setLoading(true)
    try {
      const task = await generateArtifacts(
        {
          prompt:                userInput.prompt,
          repo_url:              userInput.repo_url,
          repository_visibility: userInput.repository_visibility,
          github_token:          userInput.github_token || undefined,
          approved_artifacts:    approvedArtifacts,
        },
        envFile,
      )
      setTaskId(task.id)
      setTask(task)
      setGenerating(true)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [userInput, envFile, clearError, setLoading, setTaskId, setTask, setGenerating, setError])

  // ── Step 2b: Step-by-step — plan approved → show Cost Estimation ──────────
  // Docker artifact generation is deferred to handleApproveCostEstimation so
  // the user can review the estimated AWS cost BEFORE infra generation begins.
  const handleApproveStepByStep = useCallback(async () => {
    if (!taskId) { setError('No task ID. Re-run plan.'); return }
    const state = _store.getState()
    if (state.currentPhase !== STEP_TO_EXPECTED_PHASE['PLAN']!) {
      setError('Invalid workflow order — plan must be complete first'); return
    }
    clearError()
    // Navigate to cost estimation; docker artifacts generated after user approves cost.
    goToStep('COST_ESTIMATION')
  }, [taskId, clearError, goToStep, setError])

  // ── Step 3: Cost estimation approved → generate docker artifacts → INFRA ──
  const handleApproveCostEstimation = useCallback(async () => {
    if (!taskId) return
    clearError()
    setPhaseLoading(true)
    overlayLabelRef.current = 'Generating Docker & infrastructure artifacts…'
    lastApiCallRef.current = 'run-docker'
    try {
      const resp = await workflowRunDocker(taskId)
      mergePhaseResponse(resp)
      const fresh = await workflowGetState(taskId)
      mergePhaseResponse(fresh)
      const task = await pollTask(taskId)
      setTask(task)
      // Backend phase is now docker_completed → INFRA step
      const nextStep = PHASE_TO_STEP[fresh.current_phase]
      if (nextStep) goToStep(nextStep)
      else goToStep('INFRA')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPhaseLoading(false)
    }
  }, [taskId, clearError, setPhaseLoading, mergePhaseResponse, setTask, goToStep, setError])

  // ── Step 4: INFRA approved → start Docker build ───────────────────────────
  const handleApproveInfra = useCallback(async () => {
    if (!taskId) return
    const state = _store.getState()
    if (state.currentPhase !== STEP_TO_EXPECTED_PHASE['INFRA']!) {
      setError('Invalid workflow order — infrastructure must be generated first'); return
    }
    clearError()
    // Docker build is auto-started inside DockerBuildStep when currentPhase === docker_completed.
    goToStep('DOCKER_BUILD')
  }, [taskId, clearError, goToStep, setError])

  // ── Step 5: Docker build succeeded → run Terraform ────────────────────────
  const handleDockerBuildContinue = useCallback(async () => {
    if (!taskId) return
    const state = _store.getState()
    if (state.currentPhase !== STEP_TO_EXPECTED_PHASE['DOCKER_BUILD']!) {
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

  // ── Step 6: Terraform approved → run Kubernetes ───────────────────────────
  const handleApproveTerraform = useCallback(async () => {
    if (!taskId) return
    const state = _store.getState()
    if (state.currentPhase !== STEP_TO_EXPECTED_PHASE['TERRAFORM']!) {
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

  // ── Step 7: Kubernetes approved → run CI/CD ───────────────────────────────
  const handleApproveKubernetes = useCallback(async () => {
    if (!taskId) return
    const state = _store.getState()
    if (state.currentPhase !== STEP_TO_EXPECTED_PHASE['KUBERNETES']!) {
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

  // ── Human validation path ─────────────────────────────────────────────────
  const handleApproveHuman = useCallback(
    async (decision: PlanValidationDecision, feedback?: string) => {
      if (!taskId) { setError('No task ID.'); return }
      clearError()
      setLoading(true)
      try {
        const result = await approvePlanHumanValidation({ task_id: taskId, decision, feedback })

        if (decision === 'rejected') {
          rejectedMsgRef.current = result.message ?? 'Plan rejected.'
          return
        }

        if (decision === 'modified' && result.plan) {
          const { planPreview: current } = useWorkflowStore.getState()
          if (current) {
            setPlanPreview({
              ...current,
              plan:                result.plan,
              task_id:             result.task_id,
              requires_user_input: result.requires_user_input ?? true,
            })
          }
          return
        }

        if (decision === 'approved') {
          // Show cost estimation before generating docker artifacts
          goToStep('COST_ESTIMATION')
        }
      } catch (e) {
        setError((e as Error).message)
      } finally {
        setLoading(false)
      }
    },
    [taskId, clearError, setLoading, setPlanPreview, setError, goToStep],
  )

  const handleReset = useCallback(() => {
    rejectedMsgRef.current = null
    sessionStorage.removeItem(SESSION_KEY)
    reset()
  }, [reset])

  const showOverlay = isGenerating || isPhaseLoading

  // ── Step routing ──────────────────────────────────────────────────────────
  const stepContent = {
    INPUT: (
      <InputStep onSubmit={handlePlanPreview} isLoading={isLoading} />
    ),
    PLAN: (
      <PlanStep
        onApproveStandard={requiresHumanValidation ? handleApproveStandard : handleApproveStepByStep}
        onApproveHuman={handleApproveHuman}
        onBack={() => goToStep('INPUT')}
        isLoading={isLoading || isPhaseLoading}
        rejectedMessage={rejectedMsgRef.current}
      />
    ),
    // Cost estimation is now BEFORE infrastructure generation.
    // The user reviews the estimated AWS cost and clicks "Continue" to trigger
    // docker artifact generation, then proceeds to INFRA for review.
    COST_ESTIMATION: (
      <CostEstimationStep
        onContinue={handleApproveCostEstimation}
        onBack={() => goToStep('PLAN')}
        isPhaseLoading={isPhaseLoading}
      />
    ),
    INFRA: (
      <InfraStep
        onApprove={handleApproveInfra}
        onBack={() => goToStep('COST_ESTIMATION')}
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
    TERRAFORM: (
      <TerraformStep
        onApprove={handleApproveTerraform}
        onBack={() => goToStep('DOCKER_BUILD')}
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
      <CicdStep onApprove={() => goToStep('SUMMARY')} onBack={() => goToStep('KUBERNETES')} isLoading={isPhaseLoading} />
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
        {/* Top bar */}
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
