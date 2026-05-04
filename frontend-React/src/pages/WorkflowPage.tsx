import { useCallback, useEffect, useRef } from 'react'
import { Loader2, RotateCcw, AlertCircle, X } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

import { StepperSidebar } from '@/components/workflow/StepperSidebar'
import { InputStep }      from '@/steps/InputStep'
import { PlanStep }       from '@/steps/PlanStep'
import { InfraStep }      from '@/steps/InfraStep'
import { TerraformStep }  from '@/steps/TerraformStep'
import { KubernetesStep } from '@/steps/KubernetesStep'
import { SummaryStep }    from '@/steps/SummaryStep'
import { CicdStep }       from '@/steps/CicdStep'
import { ResultStep }     from '@/steps/ResultStep'

import { useWorkflowStore } from '@/store/workflowStore'
import {
  generatePlan,
  generateArtifacts,
  approvePlanHumanValidation,
  pollTask,
} from '@/services/workflowApi'
import { TASKS_KEY } from '@/hooks/useTasks'
import { isTerminalStatus } from '@/lib/utils'
import { cn } from '@/lib/utils'
import type { PlanValidationDecision } from '@/types'

// ── Generation overlay ────────────────────────────────────────────────────────

function GeneratingOverlay({ taskId }: { taskId?: string }) {
  const STAGES = [
    { label: 'Codebase analysis',          color: 'bg-purple-500' },
    { label: 'Infrastructure generation',   color: 'bg-cyan-500'   },
    { label: 'Terraform & Kubernetes',      color: 'bg-orange-500' },
    { label: 'CI/CD pipeline',              color: 'bg-brand-500'  },
    { label: 'Security scanning',           color: 'bg-rose-500'   },
  ]

  return (
    <div className={cn(
      'absolute inset-0 z-20 flex items-center justify-center',
      'bg-white/90 dark:bg-surface-900/90 backdrop-blur-sm',
    )}>
      <div className="w-full max-w-md px-6 space-y-6">
        {/* Header */}
        <div className={cn(
          'flex items-center gap-4 p-4 rounded-xl',
          'bg-brand-50 dark:bg-brand-600/10',
          'border border-brand-200 dark:border-brand-500/20',
        )}>
          <Loader2 className="w-5 h-5 text-brand-500 animate-spin shrink-0" />
          <div>
            <p className="text-sm font-semibold text-brand-700 dark:text-brand-300">
              AI agents are working…
            </p>
            <p className="text-xs text-brand-600/60 dark:text-brand-400/60 mt-0.5">
              Generating all infrastructure artifacts. 30–90 seconds.
            </p>
          </div>
        </div>

        {/* Stage bars */}
        <div className="space-y-3">
          {STAGES.map(({ label, color }) => (
            <div key={label}>
              <div className="flex items-center justify-between text-xs text-slate-400 dark:text-slate-500 mb-1">
                <span>{label}</span>
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

// ── Generation polling hook ───────────────────────────────────────────────────

function useGenerationPolling() {
  const {
    taskId,
    isGenerating,
    setTask,
    setGenerating,
    setError,
    goToStep,
    addLog,
  } = useWorkflowStore()
  const qc = useQueryClient()

  const stoppedRef  = useRef(false)
  const timerRef    = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!isGenerating || !taskId) return
    stoppedRef.current = false

    async function poll() {
      if (stoppedRef.current) return
      try {
        const task = await pollTask(taskId!)
        qc.setQueryData([...TASKS_KEY, taskId], task)
        qc.invalidateQueries({ queryKey: TASKS_KEY })

        // Forward new logs to the store
        if (task.logs?.length) {
          task.logs.forEach((l) => addLog(l))
        }

        const terminal = isTerminalStatus(task.status)
        const awaitingReview = task.status === 'awaiting_human_review'

        if (terminal || awaitingReview) {
          stoppedRef.current = true
          if (task.status === 'failed') {
            setError(task.error_message ?? 'Generation failed. Please try again.')
          } else {
            setTask(task)
            goToStep('INFRA')
          }
          setGenerating(false)
          return
        }
      } catch {
        // Network hiccup — keep polling
      }
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
    userInput,
    envFile,
    isLoading,
    isGenerating,
    error,
    requiresHumanValidation,
    taskId,
    setLoading,
    setGenerating,
    setError,
    clearError,
    goToStep,
    setPlanPreview,
    setTaskId,
    setTask,
    reset,
  } = useWorkflowStore()

  // Start generation polling whenever isGenerating becomes true
  useGenerationPolling()

  // ── Rejected plan message ───────────────────────────────────────────────────
  const rejectedMsgRef = useRef<string | null>(null)

  // ── Step 1: Submit form → planPreview ───────────────────────────────────────
  const handlePlanPreview = useCallback(async (file: File) => {
    clearError()
    setLoading(true)
    try {
      const preview = await generatePlan(
        {
          prompt:                userInput.prompt,
          repo_url:              userInput.repo_url,
          repository_visibility: userInput.repository_visibility,
          github_token:          userInput.github_token || undefined,
        },
        file,
      )
      setPlanPreview(preview)
      goToStep('PLAN')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [userInput, clearError, setLoading, setPlanPreview, goToStep, setError])

  // ── Step 2a: Standard path — user approves, triggers generate ───────────────
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
      // Task was created — start polling
      setTaskId(task.id)
      setTask(task)         // store initial task state
      setGenerating(true)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [userInput, envFile, clearError, setLoading, setTaskId, setTask, setGenerating, setError])

  // ── Step 2b: Human validation path ─────────────────────────────────────────
  const handleApproveHuman = useCallback(
    async (decision: PlanValidationDecision, feedback?: string) => {
      if (!taskId) {
        setError('No task ID from plan preview. Cannot validate.')
        return
      }
      clearError()
      setLoading(true)
      try {
        const result = await approvePlanHumanValidation({ task_id: taskId, decision, feedback })

        if (decision === 'rejected') {
          rejectedMsgRef.current = result.message ?? 'Plan rejected. You can start over.'
          setLoading(false)
          return
        }

        if (decision === 'approved') {
          // Backend continues running — just poll
          setGenerating(true)
        }

        if (decision === 'modified' && result.plan) {
          // Re-show updated plan
          const { planPreview: current } = useWorkflowStore.getState()
          if (current) {
            setPlanPreview({
              ...current,
              plan:                result.plan,
              task_id:             result.task_id,
              requires_user_input: result.requires_user_input ?? true,
            })
          }
        }
      } catch (e) {
        setError((e as Error).message)
      } finally {
        setLoading(false)
      }
    },
    [taskId, clearError, setLoading, setGenerating, setPlanPreview, setError],
  )

  // ── Reset ───────────────────────────────────────────────────────────────────
  const handleReset = useCallback(() => {
    rejectedMsgRef.current = null
    reset()
  }, [reset])

  // ── Step routing ────────────────────────────────────────────────────────────
  const stepContent = {
    INPUT:      <InputStep
                  onSubmit={handlePlanPreview}
                  isLoading={isLoading}
                />,
    PLAN:       <PlanStep
                  onApproveStandard={handleApproveStandard}
                  onApproveHuman={handleApproveHuman}
                  onBack={() => goToStep('INPUT')}
                  isLoading={isLoading}
                  rejectedMessage={rejectedMsgRef.current}
                />,
    INFRA:      <InfraStep
                  onApprove={() => goToStep('TERRAFORM')}
                  onBack={() => goToStep('PLAN')}
                />,
    TERRAFORM:  <TerraformStep
                  onApprove={() => goToStep('KUBERNETES')}
                  onBack={() => goToStep('INFRA')}
                />,
    KUBERNETES: <KubernetesStep
                  onApprove={() => goToStep('SUMMARY')}
                  onBack={() => goToStep('TERRAFORM')}
                />,
    SUMMARY:    <SummaryStep
                  onApprove={() => goToStep('CICD')}
                  onBack={() => goToStep('KUBERNETES')}
                />,
    CICD:       <CicdStep
                  onApprove={() => goToStep('RESULT')}
                  onBack={() => goToStep('SUMMARY')}
                  isLoading={isLoading}
                />,
    RESULT:     <ResultStep onReset={handleReset} />,
  }[currentStep]

  return (
    <div className="flex h-full bg-slate-50/50 dark:bg-transparent">
      {/* ── Left: Stepper sidebar ── */}
      <StepperSidebar />

      {/* ── Right: Step content ── */}
      <div className="flex-1 flex flex-col min-h-0 min-w-0 relative">

        {/* ── Top bar ── */}
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

        {/* ── Error banner ── */}
        {error && <ErrorBanner message={error} onDismiss={clearError} />}

        {/* ── Step content area ── */}
        <div className="flex-1 min-h-0 relative">
          {isGenerating && <GeneratingOverlay taskId={taskId} />}
          {stepContent}
        </div>
      </div>
    </div>
  )
}
