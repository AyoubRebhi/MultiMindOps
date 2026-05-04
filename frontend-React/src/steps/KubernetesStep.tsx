import { useState } from 'react'
import { Ship, AlertTriangle } from 'lucide-react'
import { StepContainer } from '@/components/workflow/StepContainer'
import { CodeEditor } from '@/components/workflow/CodeEditor'
import { useWorkflowStore } from '@/store/workflowStore'
import { getKubernetesArtifacts, displayName, artifactLanguage } from '@/services/workflowApi'
import { cn } from '@/lib/utils'

// Detect Terraform output references in kubernetes files
const TF_OUTPUT_RE = /\$\{terraform_output:[^}]+\}/

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
              ? 'bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-300'
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
}

export function KubernetesStep({ onApprove, onBack }: Props) {
  const { task, editedArtifacts, editArtifact } = useWorkflowStore()

  const artifacts = task ? getKubernetesArtifacts(task) : {}
  const keys = Object.keys(artifacts)
  const [activeKey, setActiveKey] = useState<string>(keys[0] ?? '')

  const editedKeys = new Set(Object.keys(editedArtifacts))

  const activeContent = editedArtifacts[activeKey] ?? artifacts[activeKey] ?? ''
  const hasTfRefs = TF_OUTPUT_RE.test(activeContent)

  if (!keys.length) {
    return (
      <StepContainer onBack={onBack} onApprove={onApprove} approveLabel="Continue to Summary">
        <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
          <div className="w-12 h-12 rounded-xl bg-slate-100 dark:bg-surface-800 flex items-center justify-center">
            <Ship className="w-6 h-6 text-slate-400 dark:text-slate-500" />
          </div>
          <div>
            <p className="text-sm font-medium text-slate-600 dark:text-slate-400">No Kubernetes manifests found</p>
            <p className="text-xs text-slate-400 dark:text-slate-600 mt-1">No .yaml artifacts were generated for this step.</p>
          </div>
        </div>
      </StepContainer>
    )
  }

  return (
    <StepContainer
      onBack={onBack}
      onApprove={onApprove}
      approveLabel="Approve & Continue"
    >
      <div className="space-y-4">

        {/* Context banner */}
        <div className={cn(
          'flex items-start gap-3 px-4 py-3 rounded-xl',
          'bg-blue-50 dark:bg-blue-500/10',
          'border border-blue-200 dark:border-blue-500/20',
        )}>
          <Ship className="w-4 h-4 text-blue-600 dark:text-blue-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-blue-800 dark:text-blue-200">
              Kubernetes Manifests — {keys.length} file{keys.length > 1 ? 's' : ''} generated
            </p>
            <p className="text-xs text-blue-700/70 dark:text-blue-400/60 mt-0.5">
              Container orchestration configuration. Deployments, services, ingress, and HPA.
            </p>
          </div>
        </div>

        {/* Terraform contract notice */}
        {hasTfRefs && (
          <div className={cn(
            'flex items-start gap-2 px-3 py-2.5 rounded-lg',
            'bg-orange-50 dark:bg-orange-500/10',
            'border border-orange-200 dark:border-orange-500/20',
          )}>
            <AlertTriangle className="w-3.5 h-3.5 text-orange-500 dark:text-orange-400 shrink-0 mt-0.5" />
            <p className="text-xs text-orange-700 dark:text-orange-300">
              <span className="font-semibold">Terraform contract references detected.</span>{' '}
              Values like{' '}
              <code className="font-mono bg-orange-100 dark:bg-orange-500/20 px-1 rounded">
                {'${terraform_output:cluster_endpoint}'}
              </code>{' '}
              are injected from Terraform outputs at deploy time.
            </p>
          </div>
        )}

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
              value={activeContent}
              onChange={(v) => editArtifact(activeKey, v)}
              height="480px"
            />
          )}
        </div>
      </div>
    </StepContainer>
  )
}
