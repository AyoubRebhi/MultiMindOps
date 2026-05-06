import { useState } from 'react'
import { Container, FolderOpen, Loader2 } from 'lucide-react'
import { StepContainer } from '@/components/workflow/StepContainer'
import { CodeEditor } from '@/components/workflow/CodeEditor'
import { useWorkflowStore } from '@/store/workflowStore'
import { getInfraArtifacts, displayName, artifactLanguage } from '@/services/workflowApi'
import { cn } from '@/lib/utils'

// ── File tab bar ──────────────────────────────────────────────────────────────

function FileTabs({
  keys,
  active,
  onChange,
  editedKeys,
}: {
  keys: string[]
  active: string
  onChange: (k: string) => void
  editedKeys: Set<string>
}) {
  return (
    <div className={cn(
      'flex gap-1 overflow-x-auto pb-1',
      'border-b border-slate-200 dark:border-white/[0.06]',
      'bg-slate-50 dark:bg-surface-800/30 px-4 pt-3',
    )}>
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
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" title="Edited" />
          )}
        </button>
      ))}
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

// ── Main ──────────────────────────────────────────────────────────────────────

interface Props {
  onApprove: () => void
  onBack: () => void
  isPhaseLoading?: boolean
}

export function InfraStep({ onApprove, onBack, isPhaseLoading }: Props) {
  const { task, editedArtifacts, editArtifact, currentPhase } = useWorkflowStore()

  const artifacts = task ? getInfraArtifacts(task) : {}
  const keys = Object.keys(artifacts)
  const [activeKey, setActiveKey] = useState<string>(keys[0] ?? '')

  const editedKeys = new Set(Object.keys(editedArtifacts))

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
    ? 'Generating Terraform…'
    : 'Approve & Run Terraform'

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
              Review and optionally edit Docker configuration files. Changes are tracked locally.
            </p>
          </div>
        </div>

        {/* File tabs + editor */}
        <div className="rounded-xl border border-slate-200 dark:border-white/[0.06] overflow-hidden bg-white dark:bg-surface-900">
          {keys.length > 1 && (
            <FileTabs
              keys={keys}
              active={activeKey}
              onChange={setActiveKey}
              editedKeys={editedKeys}
            />
          )}

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
