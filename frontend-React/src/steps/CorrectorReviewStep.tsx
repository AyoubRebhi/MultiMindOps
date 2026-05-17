import { useCallback, useEffect, useRef, useState } from 'react'
import { Wrench, AlertCircle, Loader2, ShieldAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useWorkflowStore, hasExecutionFailed, canRetryBuild } from '@/store/workflowStore'
import {
  getCorrectorAnalysis,
  reanalyze,
  isAnalysisRunning,
  type CorrectorStatusResponse,
} from '@/services/correctorApi'
import { applyAiPatch, retryDockerBuild, resetArtifact, type ArtifactKey } from '@/services/workflowApi'

import { FailureSummaryCard }   from '@/components/corrector/FailureSummaryCard'
import { ErrorLogPanel }         from '@/components/corrector/ErrorLogPanel'
import { AIDiagnosisPanel }      from '@/components/corrector/AIDiagnosisPanel'
import { SuggestedFixCard }      from '@/components/corrector/SuggestedFixCard'
import { RemediationActionBar }  from '@/components/corrector/RemediationActionBar'
import { EditableArtifactTabs } from '@/components/corrector/EditableArtifactTabs'

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  onRetryBuild: () => void
  onBackToInfra: () => void
  onStopWorkflow: () => void
}

// ── Section heading ───────────────────────────────────────────────────────────

function SectionHeading({ label, count }: { label: string; count?: number }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">{label}</p>
      {count != null && (
        <span className="text-[10px] font-mono text-slate-600 bg-slate-800 border border-slate-700 px-2 py-0.5 rounded-full">
          {count}
        </span>
      )}
      <div className="flex-1 h-px bg-slate-800" />
    </div>
  )
}

// ── Skeleton loader ───────────────────────────────────────────────────────────

function CorrectorSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-32 rounded-xl bg-slate-800/60" />
      <div className="h-48 rounded-xl bg-slate-800/40" />
      <div className="h-24 rounded-xl bg-slate-800/50" />
      <div className="h-40 rounded-xl bg-slate-800/30" />
    </div>
  )
}

// ── Exhausted state ───────────────────────────────────────────────────────────

function ExhaustedBanner() {
  return (
    <div className={cn(
      'flex items-start gap-4 px-5 py-4 rounded-xl',
      'bg-red-500/8 border border-red-500/25',
    )}>
      <div className="shrink-0 w-10 h-10 rounded-xl flex items-center justify-center bg-red-500/15">
        <ShieldAlert className="w-5 h-5 text-red-400" />
      </div>
      <div>
        <p className="text-sm font-bold text-red-300 mb-1">🚨 Automatic remediation limit reached</p>
        <p className="text-xs text-red-400/70 leading-relaxed">
          All automated retry attempts have been exhausted. The AI corrector has analyzed the failure
          on each attempt. Please inspect the Dockerfile and infrastructure artifacts manually,
          apply the suggested patches, and restart the workflow from the Infrastructure step.
        </p>
        <ul className="mt-3 space-y-1">
          {['Review the suggested patches below', 'Edit the Dockerfile in the Infrastructure step', 'Resubmit to start a new build sequence'].map((hint) => (
            <li key={hint} className="flex items-center gap-2 text-xs text-red-400/60">
              <span className="w-1 h-1 rounded-full bg-red-500/60 shrink-0" />
              {hint}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function CorrectorReviewStep({ onRetryBuild, onBackToInfra, onStopWorkflow }: Props) {
  const { taskId, currentPhase, setCorrectorData, correctorData, mergePhaseResponse } = useWorkflowStore()

  const [localData, setLocalData]       = useState<CorrectorStatusResponse | undefined>(correctorData)
  const [fetchError, setFetchError]     = useState<string>()
  const [isFetching, setIsFetching]     = useState(!correctorData)
  const [isRetrying, setIsRetrying]     = useState(false)
  const [isReanalyzing, setIsReanalyzing] = useState(false)
  const [reanalyzeError, setReanalyzeError] = useState<string>()
  const [hasUnsavedArtifacts, setHasUnsavedArtifacts] = useState(false)
  const [artifactRefresh, setArtifactRefresh] = useState(0)

  const pollingRef   = useRef<ReturnType<typeof setInterval> | null>(null)
  const isMountedRef = useRef(true)

  // ── Fetch corrector data on mount ─────────────────────────────────────────
  useEffect(() => {
    if (!taskId) return
    isMountedRef.current = true

    async function fetch() {
      setIsFetching(true)
      setFetchError(undefined)
      try {
        const data = await getCorrectorAnalysis(taskId!)
        if (!isMountedRef.current) return
        setLocalData(data)
        setCorrectorData(data)
      } catch (e) {
        if (isMountedRef.current) setFetchError((e as Error).message)
      } finally {
        if (isMountedRef.current) setIsFetching(false)
      }
    }

    fetch()

    return () => {
      isMountedRef.current = false
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId])

  // ── Poll while analysis is running ────────────────────────────────────────
  useEffect(() => {
    const running = isAnalysisRunning(localData?.current_phase ?? currentPhase)
    if (!running || !taskId) {
      if (pollingRef.current) clearInterval(pollingRef.current)
      return
    }

    pollingRef.current = setInterval(async () => {
      try {
        const data = await getCorrectorAnalysis(taskId)
        if (!isMountedRef.current) return
        setLocalData(data)
        setCorrectorData(data)
        if (!isAnalysisRunning(data.current_phase)) {
          if (pollingRef.current) clearInterval(pollingRef.current)
        }
      } catch { /* ignore polling errors */ }
    }, 3_000)

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, localData?.current_phase, currentPhase])

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleApproveRetry = useCallback(async () => {
    if (!taskId) return
    if (hasUnsavedArtifacts && !window.confirm('You have unsaved artifact edits. Retry will use the latest saved version, not the draft. Continue?')) return
    setIsRetrying(true)
    try {
      await retryDockerBuild(taskId)
      mergePhaseResponse({
        task_id: taskId,
        current_phase: 'docker_build_running',
        status: 'in_progress',
        artifacts: {},
        terraform_outputs: {},
        logs: [],
        message: '',
      })
      onRetryBuild()
    } catch (e) {
      setFetchError((e as Error).message)
    } finally {
      setIsRetrying(false)
    }
  }, [taskId, hasUnsavedArtifacts, mergePhaseResponse, onRetryBuild])

  const handleApplyAiPatchRetry = useCallback(async () => {
    if (!taskId) return
    if (hasUnsavedArtifacts && !window.confirm('Applying the AI patch will save over the current artifact version. Continue?')) return
    setIsRetrying(true)
    try {
      await applyAiPatch(taskId)
      setArtifactRefresh((v) => v + 1)
      await retryDockerBuild(taskId)
      mergePhaseResponse({
        task_id: taskId,
        current_phase: 'docker_build_running',
        status: 'in_progress',
        artifacts: {},
        terraform_outputs: {},
        logs: [],
        message: '',
      })
      onRetryBuild()
    } catch (e) {
      setFetchError((e as Error).message)
    } finally {
      setIsRetrying(false)
    }
  }, [taskId, hasUnsavedArtifacts, mergePhaseResponse, onRetryBuild])

  const handleResetAllOriginal = useCallback(async () => {
    if (!taskId) return
    if (!window.confirm('Reset Dockerfile, Docker Compose, and .dockerignore to their original generated versions?')) return
    setIsRetrying(true)
    try {
      await Promise.allSettled((['dockerfile', 'docker_compose', 'dockerignore'] as ArtifactKey[]).map((key) => resetArtifact(taskId, key)))
      setArtifactRefresh((v) => v + 1)
      setHasUnsavedArtifacts(false)
    } catch (e) {
      setFetchError((e as Error).message)
    } finally {
      setIsRetrying(false)
    }
  }, [taskId])

  const handleReanalyze = useCallback(async () => {
    if (!taskId) return
    setIsReanalyzing(true)
    setReanalyzeError(undefined)
    try {
      await reanalyze(taskId)
      // Immediately mark phase as running in local state for UI feedback
      setLocalData((prev) => prev
        ? { ...prev, current_phase: 'corrector_analysis_running' }
        : prev,
      )
    } catch (e) {
      setReanalyzeError((e as Error).message)
    } finally {
      setIsReanalyzing(false)
    }
  }, [taskId])

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasUnsavedArtifacts) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [hasUnsavedArtifacts])

  // ── Derived state ─────────────────────────────────────────────────────────

  const phase       = localData?.current_phase ?? currentPhase
  const analysis    = localData?.analysis
  const retryCount  = localData?.retry_count ?? 0
  const maxRetries  = localData?.max_retries ?? 3
  const execFailed  = hasExecutionFailed(phase)
  const analysisRunning = isAnalysisRunning(phase)
  const canRetry    = canRetryBuild(retryCount, maxRetries) && !execFailed
  const fixes       = analysis?.fixes ?? []

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full min-h-0 bg-[#080b12]">
      {/* Page header */}
      <div className={cn(
        'shrink-0 flex items-center gap-4 px-6 py-4',
        'border-b border-slate-800 bg-[#0a0d14]',
      )}>
        <div className={cn(
          'w-9 h-9 rounded-xl flex items-center justify-center shrink-0',
          execFailed
            ? 'bg-red-500/15 border border-red-500/25'
            : 'bg-amber-500/15 border border-amber-500/25',
        )}>
          <Wrench className={cn('w-5 h-5', execFailed ? 'text-red-400' : 'text-amber-400')} />
        </div>
        <div>
          <h2 className="text-base font-bold text-slate-100 leading-tight">
            AI Remediation Review
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            {analysisRunning
              ? 'AI corrector is analyzing the build failure…'
              : execFailed
              ? 'Automated remediation exhausted — manual review required'
              : 'Review AI-suggested fixes before retrying the build'}
          </p>
        </div>

        {analysisRunning && (
          <div className="ml-auto flex items-center gap-2 text-xs text-purple-300 font-mono animate-pulse">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Analyzing logs…
          </div>
        )}
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">

        {/* Error fetching */}
        {fetchError && (
          <div className={cn(
            'flex items-start gap-3 px-4 py-3 rounded-xl',
            'bg-red-500/8 border border-red-500/20',
          )}>
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <p className="text-sm text-red-300">{fetchError}</p>
          </div>
        )}

        {reanalyzeError && (
          <div className={cn(
            'flex items-start gap-3 px-4 py-3 rounded-xl',
            'bg-orange-500/8 border border-orange-500/20',
          )}>
            <AlertCircle className="w-4 h-4 text-orange-400 shrink-0 mt-0.5" />
            <p className="text-sm text-orange-300">{reanalyzeError}</p>
          </div>
        )}

        {/* Skeleton */}
        {isFetching && !localData && <CorrectorSkeleton />}

        {/* Exhausted banner */}
        {!isFetching && execFailed && <ExhaustedBanner />}

        {/* ── SECTION 1: Failure Summary ─────────────────────────────────── */}
        {analysis && (
          <>
            <div>
              <SectionHeading label="Failure Summary" />
              <FailureSummaryCard
                analysis={analysis}
                retryCount={retryCount}
                maxRetries={maxRetries}
                executionFailed={execFailed}
              />
            </div>

            {/* ── SECTION 2: Error Output ───────────────────────────────── */}
            {analysis.error_excerpt && (
              <div>
                <SectionHeading label="Error Output" />
                <ErrorLogPanel
                  errorExcerpt={analysis.error_excerpt}
                  title="Docker Build Error Excerpt"
                />
              </div>
            )}
          </>
        )}

        {/* ── SECTION 3: AI Diagnosis ────────────────────────────────────── */}
        <div>
          <SectionHeading label="AI Diagnosis" />
          <AIDiagnosisPanel
            analysis={analysis ?? {}}
            isRunning={analysisRunning || (isFetching && !localData)}
          />
        </div>

        {/* ── SECTION 4: Suggested Fixes ────────────────────────────────── */}
        {fixes.length > 0 && (
          <div>
            <SectionHeading label="Suggested Fixes" count={fixes.length} />
            <div className="space-y-3">
              {fixes.map((fix, i) => (
                <SuggestedFixCard
                  key={i}
                  fix={fix}
                  index={i}
                  defaultOpen={i === 0}
                />
              ))}
            </div>
          </div>
        )}

        {taskId && (
          <div>
            <SectionHeading label="Manual Artifact Correction" />
            <EditableArtifactTabs
              taskId={taskId}
              refreshToken={artifactRefresh}
              onDirtyChange={setHasUnsavedArtifacts}
            />
          </div>
        )}

        {/* Empty state when no fixes and analysis complete */}
        {!isFetching && !analysisRunning && fixes.length === 0 && analysis && (
          <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-slate-700 bg-slate-800/30">
            <AlertCircle className="w-4 h-4 text-slate-500 shrink-0" />
            <p className="text-sm text-slate-400">
              No specific fixes were generated. Review the error output and AI diagnosis above.
            </p>
          </div>
        )}

        {/* Spacer to ensure action bar doesn't overlap last content */}
        <div className="h-4" />
      </div>

      {/* ── SECTION 5: Action Bar ─────────────────────────────────────────── */}
      <div className="shrink-0 px-6 pb-5">
        <RemediationActionBar
          canRetry={canRetry}
          isRetrying={isRetrying}
          isReanalyzing={isReanalyzing}
          executionFailed={execFailed}
          onApproveRetry={handleApproveRetry}
          onApplyAiPatchRetry={handleApplyAiPatchRetry}
          onResetOriginal={handleResetAllOriginal}
          onReanalyze={handleReanalyze}
          onBackToInfra={onBackToInfra}
          onStopWorkflow={onStopWorkflow}
        />
      </div>
    </div>
  )
}
