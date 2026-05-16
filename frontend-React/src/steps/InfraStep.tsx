import { useEffect, useRef, useState } from 'react'
import {
  Container, FolderOpen, Loader2,
  Server, Globe, Zap, Database, AlertTriangle, CheckCircle2,
  Save, RotateCcw,
} from 'lucide-react'
import { StepContainer } from '@/components/workflow/StepContainer'
import { CodeEditor } from '@/components/workflow/CodeEditor'
import { useWorkflowStore } from '@/store/workflowStore'
import { getInfraArtifacts, displayName, artifactLanguage, patchArtifacts, resetArtifact } from '@/services/workflowApi'
import type { ArtifactKey } from '@/services/workflowApi'
import type { TopologySummary } from '@/services/workflowApi'
import { cn } from '@/lib/utils'

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

// ── File tab bar ──────────────────────────────────────────────────────────────

function SaveIndicator({ status }: { status: SaveStatus }) {
  if (status === 'idle') return null
  return (
    <div className={cn(
      'flex items-center gap-1.5 text-[11px] font-medium px-2 py-1 rounded-md',
      status === 'saving' && 'text-slate-400 dark:text-slate-500',
      status === 'saved'  && 'text-emerald-600 dark:text-emerald-400',
      status === 'error'  && 'text-red-600 dark:text-red-400',
    )}>
      {status === 'saving' && <Loader2 className="w-3 h-3 animate-spin" />}
      {status === 'saved'  && <Save className="w-3 h-3" />}
      {status === 'error'  && <AlertTriangle className="w-3 h-3" />}
      {status === 'saving' ? 'Saving…' : status === 'saved' ? 'Saved' : 'Save failed'}
    </div>
  )
}

function FileTabs({
  keys,
  active,
  onChange,
  editedKeys,
  saveStatus,
}: {
  keys: string[]
  active: string
  onChange: (k: string) => void
  editedKeys: Set<string>
  saveStatus: SaveStatus
}) {
  return (
    <div className={cn(
      'flex items-end justify-between gap-1 overflow-x-auto pb-1',
      'border-b border-slate-200 dark:border-white/[0.06]',
      'bg-slate-50 dark:bg-surface-800/30 px-4 pt-3',
    )}>
      <div className="flex gap-1 overflow-x-auto">
        {keys.map((k) => (
          <button
            key={k}
            onClick={() => onChange(k)}
            className={cn(
              'shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-t-lg text-xs font-mono font-medium transition-colors border border-b-0',
              active === k
                ? cn(
                    'bg-white dark:bg-surface-900',
                    'border-slate-200 dark:border-white/[0.08]',
                    'text-slate-800 dark:text-slate-200',
                    '-mb-px pb-2',
                  )
                : cn(
                    'bg-transparent border-transparent',
                    'text-slate-400 dark:text-slate-500',
                    'hover:text-slate-600 dark:hover:text-slate-300',
                    'hover:bg-slate-100 dark:hover:bg-white/[0.04]',
                  ),
            )}
          >
            {displayName(k)}
            {editedKeys.has(k) && (
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" title="Unsaved changes" />
            )}
          </button>
        ))}
      </div>
      <SaveIndicator status={saveStatus} />
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyArtifacts({ icon: Icon, label }: { icon: React.ElementType; label: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <div className="w-12 h-12 rounded-xl bg-slate-100 dark:bg-surface-800 flex items-center justify-center">
        <Icon className="w-6 h-6 text-slate-400 dark:text-slate-500" />
      </div>
      <div>
        <p className="text-sm font-medium text-slate-600 dark:text-slate-400">{label}</p>
        <p className="text-xs text-slate-400 dark:text-slate-600 mt-1">
          No artifacts were generated for this step.
        </p>
      </div>
    </div>
  )
}

// ── Topology panel ────────────────────────────────────────────────────────────

const MODE_STYLE: Record<string, string> = {
  development: 'text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/20',
  staging:     'text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-500/10 border-blue-200 dark:border-blue-500/20',
  production:  'text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/20',
}

function TopologyPanel({ summary }: { summary: TopologySummary }) {
  const modeStyle = MODE_STYLE[summary.runtime_mode] ?? MODE_STYLE.production
  const hasIssues = !summary.build_context_valid || summary.build_context_issues.length > 0

  return (
    <div className={cn(
      'rounded-xl border px-4 py-3 space-y-3',
      'bg-slate-50 dark:bg-surface-800/30',
      'border-slate-200 dark:border-white/[0.06]',
    )}>
      {/* Header row */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Server className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wide">
            Infrastructure Context
          </span>
        </div>
        <span className={cn('text-[10px] font-semibold px-2 py-0.5 rounded-full border uppercase tracking-wide', modeStyle)}>
          {summary.runtime_mode}{summary.hot_reload ? ' · hot-reload' : ''}
        </span>
      </div>

      {/* Detail grid */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
        {summary.backend_service && (
          <TopologyRow icon={<Server className="w-3 h-3" />} label="Backend service" value={summary.backend_service} />
        )}
        <TopologyRow icon={<FolderOpen className="w-3 h-3" />} label="Build context" value={summary.build_context} mono />
        {summary.framework && (
          <TopologyRow icon={<Zap className="w-3 h-3" />} label="Framework" value={`${summary.framework}${summary.language ? ` (${summary.language})` : ''}`} />
        )}
        {summary.port !== undefined && (
          <TopologyRow icon={<Globe className="w-3 h-3" />} label="Port" value={String(summary.port)} mono />
        )}
        {summary.dependency_file && (
          <TopologyRow icon={<FolderOpen className="w-3 h-3" />} label="Dependencies" value={summary.dependency_file} mono />
        )}
        {summary.entrypoint && (
          <TopologyRow icon={<Zap className="w-3 h-3" />} label="Entrypoint" value={summary.entrypoint} mono truncate />
        )}
        {(summary.has_db || summary.has_cache) && (
          <TopologyRow
            icon={<Database className="w-3 h-3" />}
            label="Services"
            value={[summary.has_db && 'database', summary.has_cache && 'cache'].filter(Boolean).join(', ')}
          />
        )}
        {summary.is_monorepo && (
          <TopologyRow icon={<FolderOpen className="w-3 h-3" />} label="Layout" value="monorepo" />
        )}
        {summary.compose_services.length > 0 && (
          <div className="col-span-2 flex items-start gap-1.5 text-slate-500 dark:text-slate-400">
            <Server className="w-3 h-3 shrink-0 mt-0.5 text-slate-400" />
            <span className="text-slate-400 dark:text-slate-500 w-20 shrink-0">Compose</span>
            <span className="font-mono text-slate-600 dark:text-slate-300">
              {summary.compose_services.join(', ')}
            </span>
          </div>
        )}
      </div>

      {/* Validation status */}
      <div className="flex items-center gap-1.5 pt-1 border-t border-slate-200 dark:border-white/[0.04]">
        {hasIssues ? (
          <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
        ) : (
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
        )}
        <span className={cn(
          'text-xs',
          hasIssues ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400',
        )}>
          {hasIssues
            ? `Build context issue: ${summary.build_context_issues[0] ?? 'validation warning'}`
            : 'Build context validated'
          }
        </span>
      </div>

      {/* Warnings */}
      {summary.build_context_warnings.length > 0 && (
        <ul className="space-y-0.5">
          {summary.build_context_warnings.slice(0, 3).map((w, i) => (
            <li key={i} className="flex items-start gap-1.5 text-[11px] text-amber-600 dark:text-amber-400">
              <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
              {w}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function TopologyRow({
  icon,
  label,
  value,
  mono = false,
  truncate = false,
}: {
  icon: React.ReactNode
  label: string
  value: string
  mono?: boolean
  truncate?: boolean
}) {
  return (
    <div className="flex items-start gap-1.5 text-slate-500 dark:text-slate-400">
      <span className="shrink-0 mt-0.5 text-slate-400">{icon}</span>
      <span className="text-slate-400 dark:text-slate-500 w-24 shrink-0">{label}</span>
      <span className={cn(
        'text-slate-700 dark:text-slate-200',
        mono && 'font-mono',
        truncate && 'truncate max-w-[180px]',
      )}>
        {value}
      </span>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

interface Props {
  onApprove: () => void
  onBack: () => void
  isPhaseLoading?: boolean
}

const INFRA_ARTIFACT_KEYS = new Set(['dockerfile', 'dockerignore', 'docker_compose', 'env_example'])

export function InfraStep({ onApprove, onBack, isPhaseLoading }: Props) {
  const { task, taskId, phaseArtifacts, editedArtifacts, editArtifact, currentPhase, topologySummary } = useWorkflowStore()

  // Primary: task.infra.artifacts (enriched by setTask with phaseArtifacts)
  // Fallback: phaseArtifacts filtered to Docker keys (belt-and-suspenders for
  //           edge cases where setTask was not called before navigation)
  const taskArtifacts = task ? getInfraArtifacts(task) : {}
  const fallbackArtifacts = Object.fromEntries(
    Object.entries(phaseArtifacts).filter(([k]) => INFRA_ARTIFACT_KEYS.has(k) || k.startsWith('docker_'))
  )
  const artifacts = Object.keys(taskArtifacts).length > 0 ? taskArtifacts : fallbackArtifacts

  // Topology summary: prefer phase-level (real-time) over task-level (polled)
  const topologyFromTask = (task?.infra as { topology_summary?: TopologySummary } | undefined)?.topology_summary
  const resolvedTopology = topologySummary ?? topologyFromTask

  console.log('[InfraUI] currentPhase:', currentPhase)
  console.log('[InfraUI] task?.infra?.artifacts keys:', Object.keys(task?.infra?.artifacts ?? {}))
  console.log('[InfraUI] taskArtifacts keys:', Object.keys(taskArtifacts))
  console.log('[InfraUI] phaseArtifacts (docker) keys:', Object.keys(fallbackArtifacts))
  console.log('[InfraUI] resolved artifacts keys:', Object.keys(artifacts))

  const keys = Object.keys(artifacts)
  const [activeKey, setActiveKey] = useState<string>(keys[0] ?? '')
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')

  const editedKeys = new Set(Object.keys(editedArtifacts))

  // ── Autosave: debounce 1.5s after any edit ────────────────────────────────
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!taskId || Object.keys(editedArtifacts).length === 0) return

    setSaveStatus('idle')
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current)

    autosaveTimerRef.current = setTimeout(async () => {
      const dockerKeys = ['dockerfile', 'dockerignore', 'docker_compose', 'env_example'] as const
      const toSave = Object.fromEntries(
        Object.entries(editedArtifacts).filter(([k]) => (dockerKeys as readonly string[]).includes(k))
      ) as Partial<Record<typeof dockerKeys[number], string>>
      if (Object.keys(toSave).length === 0) return

      setSaveStatus('saving')
      console.log('[ArtifactEditor] Autosave started — keys:', Object.keys(toSave))
      try {
        await patchArtifacts(taskId, toSave)
        setSaveStatus('saved')
        console.log('[ArtifactEditor] Autosave success — versions persisted')
        setTimeout(() => setSaveStatus('idle'), 3000)
      } catch (err) {
        setSaveStatus('error')
        console.error('[ArtifactEditor] Autosave failed:', err)
      }
    }, 1500)

    return () => {
      if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editedArtifacts, taskId])

  // Safety check: backend must be in `docker_completed` phase before this
  // step is allowed to render. If we got here with the wrong phase, bail out
  // rather than letting the user click "Approve & Run Terraform" and hit a 409.
  if (currentPhase !== 'docker_completed') {
    return (
      <StepContainer onBack={onBack} hideActions>
        <div className={cn(
          'flex items-start gap-3 px-4 py-3 rounded-xl',
          'bg-red-50 dark:bg-red-500/10',
          'border border-red-200 dark:border-red-500/20',
        )}>
          <Container className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-red-700 dark:text-red-300">
              Docker phase not completed
            </p>
            <p className="text-xs text-red-600/70 dark:text-red-400/60 mt-0.5">
              Backend phase is "{currentPhase || 'unknown'}", expected "docker_completed".
              Go back and approve the plan to run the Docker phase.
            </p>
          </div>
        </div>
      </StepContainer>
    )
  }

  const approveLabel = isPhaseLoading
    ? 'Starting Build…'
    : 'Approve & Build Docker Image'

  if (!keys.length) {
    return (
      <StepContainer onBack={onBack} onApprove={onApprove} approveLabel={approveLabel} approveDisabled={isPhaseLoading}>
        <EmptyArtifacts icon={Container} label="No Docker artifacts found" />
        {isPhaseLoading && <div className="flex justify-center py-4"><Loader2 className="w-5 h-5 animate-spin text-brand-500" /></div>}
      </StepContainer>
    )
  }

  return (
    <StepContainer
      onBack={onBack}
      onApprove={onApprove}
      approveLabel={approveLabel}
      approveDisabled={isPhaseLoading}
    >
      <div className="space-y-4">

        {/* Context banner */}
        <div className={cn(
          'flex items-start gap-3 px-4 py-3 rounded-xl',
          'bg-cyan-50 dark:bg-cyan-500/10',
          'border border-cyan-200 dark:border-cyan-500/20',
        )}>
          <Container className="w-4 h-4 text-cyan-600 dark:text-cyan-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-cyan-800 dark:text-cyan-200">
              Infrastructure Artifacts — {keys.length} file{keys.length > 1 ? 's' : ''} generated
            </p>
            <p className="text-xs text-cyan-700/70 dark:text-cyan-400/60 mt-0.5">
              Review and optionally edit Docker configuration files. After approval, the image will be built locally.
            </p>
          </div>
        </div>

        {/* Topology panel — shown when the grounding layer produced metadata */}
        {resolvedTopology && <TopologyPanel summary={resolvedTopology} />}

        {/* File tabs + editor */}
        <div className="rounded-xl border border-slate-200 dark:border-white/[0.06] overflow-hidden bg-white dark:bg-surface-900">
          {keys.length > 1 ? (
            <FileTabs
              keys={keys}
              active={activeKey}
              onChange={setActiveKey}
              editedKeys={editedKeys}
              saveStatus={saveStatus}
            />
          ) : activeKey ? (
            /* Single-file header: filename + save indicator + reset button */
            <div className={cn(
              'flex items-center justify-between px-4 py-2',
              'bg-slate-50 dark:bg-surface-800/30',
              'border-b border-slate-200 dark:border-white/[0.06]',
            )}>
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono font-medium text-slate-600 dark:text-slate-300">
                  {displayName(activeKey)}
                </span>
                {editedKeys.has(activeKey) && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300 font-medium">
                    edited
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <SaveIndicator status={saveStatus} />
                {editedKeys.has(activeKey) && taskId && (
                  <button
                    onClick={async () => {
                      try {
                        await resetArtifact(taskId, activeKey as ArtifactKey)
                        editArtifact(activeKey, artifacts[activeKey] ?? '')
                        setSaveStatus('idle')
                        console.log('[ArtifactEditor] Reset artifact:', activeKey)
                      } catch (err) {
                        console.error('[ArtifactEditor] Reset failed:', err)
                      }
                    }}
                    className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
                    title="Reset to generated content"
                  >
                    <RotateCcw className="w-3 h-3" />
                    Reset
                  </button>
                )}
              </div>
            </div>
          ) : null}

          {activeKey && (
            <CodeEditor
              key={activeKey}
              filename={displayName(activeKey)}
              language={artifactLanguage(activeKey)}
              value={editedArtifacts[activeKey] ?? artifacts[activeKey] ?? ''}
              onChange={(v) => editArtifact(activeKey, v)}
              height="480px"
            />
          )}
        </div>

        {/* File list for large sets */}
        {keys.length > 4 && (
          <div className={cn(
            'flex items-center gap-2 px-4 py-3 rounded-xl text-xs',
            'bg-slate-50 dark:bg-surface-800/30',
            'border border-slate-200 dark:border-white/[0.04]',
          )}>
            <FolderOpen className="w-3.5 h-3.5 text-slate-400 shrink-0" />
            <span className="text-slate-500 dark:text-slate-400">
              {keys.length} files total.
            </span>
            <div className="flex flex-wrap gap-1">
              {keys.map((k) => (
                <button
                  key={k}
                  onClick={() => setActiveKey(k)}
                  className={cn(
                    'px-2 py-0.5 rounded font-mono transition-colors',
                    activeKey === k
                      ? 'bg-brand-100 dark:bg-brand-600/20 text-brand-700 dark:text-brand-300'
                      : 'text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300',
                  )}
                >
                  {displayName(k)}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </StepContainer>
  )
}
