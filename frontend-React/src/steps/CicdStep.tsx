import { useState } from 'react'
import { GitBranch } from 'lucide-react'
import { StepContainer } from '@/components/workflow/StepContainer'
import { CodeEditor } from '@/components/workflow/CodeEditor'
import { useWorkflowStore } from '@/store/workflowStore'
import { getCicdArtifacts, displayName, artifactLanguage } from '@/services/workflowApi'
import { cn } from '@/lib/utils'

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
    <div className="flex flex-wrap gap-1 px-4 py-3 border-b border-slate-200 dark:border-white/[0.06] bg-slate-50 dark:bg-surface-800/30">
      {keys.map((k) => (
        <button
          key={k}
          onClick={() => onChange(k)}
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-mono font-medium transition-colors',
            active === k
              ? 'bg-purple-100 dark:bg-purple-500/20 text-purple-700 dark:text-purple-300'
              : 'text-slate-400 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/[0.05]',
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

interface Props {
  onApprove: () => void
  onBack: () => void
  isLoading?: boolean
}

export function CicdStep({ onApprove, onBack, isLoading }: Props) {
  const { task, editedArtifacts, editArtifact } = useWorkflowStore()

  const artifacts = task ? getCicdArtifacts(task) : {}
  const keys = Object.keys(artifacts)
  const [activeKey, setActiveKey] = useState<string>(keys[0] ?? '')

  const editedKeys = new Set(Object.keys(editedArtifacts))

  if (!keys.length) {
    return (
      <StepContainer
        onBack={onBack}
        onApprove={onApprove}
        approveLabel="Complete Review"
        isLoading={isLoading}
      >
        <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
          <div className="w-12 h-12 rounded-xl bg-slate-100 dark:bg-surface-800 flex items-center justify-center">
            <GitBranch className="w-6 h-6 text-slate-400 dark:text-slate-500" />
          </div>
          <div>
            <p className="text-sm font-medium text-slate-600 dark:text-slate-400">No CI/CD workflows found</p>
            <p className="text-xs text-slate-400 dark:text-slate-600 mt-1">No GitHub Actions workflows were generated.</p>
          </div>
        </div>
      </StepContainer>
    )
  }

  return (
    <StepContainer
      onBack={onBack}
      onApprove={onApprove}
      approveLabel="Complete Review & Save"
      isLoading={isLoading}
    >
      <div className="space-y-4">

        {/* Context banner */}
        <div className={cn(
          'flex items-start gap-3 px-4 py-3 rounded-xl',
          'bg-purple-50 dark:bg-purple-500/10',
          'border border-purple-200 dark:border-purple-500/20',
        )}>
          <GitBranch className="w-4 h-4 text-purple-600 dark:text-purple-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-purple-800 dark:text-purple-200">
              CI/CD Workflows — {keys.length} file{keys.length > 1 ? 's' : ''} generated
            </p>
            <p className="text-xs text-purple-700/70 dark:text-purple-400/60 mt-0.5">
              GitHub Actions pipeline with build, test, security scanning, and deployment stages.
            </p>
          </div>
        </div>

        {/* Editor */}
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
              height="520px"
            />
          )}
        </div>
      </div>
    </StepContainer>
  )
}
