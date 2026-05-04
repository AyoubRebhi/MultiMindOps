import { useState } from 'react'
import { Layers, ArrowRight, Server, Network, Container, Globe } from 'lucide-react'
import { StepContainer } from '@/components/workflow/StepContainer'
import { CodeEditor } from '@/components/workflow/CodeEditor'
import { useWorkflowStore } from '@/store/workflowStore'
import {
  getTerraformArtifacts,
  displayName,
  artifactLanguage,
} from '@/services/workflowApi'
import { cn } from '@/lib/utils'
import type { TerraformOutputs } from '@/types'

// ── Terraform outputs mini-table ──────────────────────────────────────────────

const OUTPUT_META: Partial<Record<keyof TerraformOutputs, { label: string; icon: React.ElementType; color: string }>> = {
  cluster_endpoint:  { label: 'Cluster Endpoint',    icon: Server,    color: 'text-blue-500'    },
  cluster_name:      { label: 'Cluster Name',         icon: Server,    color: 'text-indigo-500'  },
  ecr_repository_url:{ label: 'ECR Repository URL',   icon: Container, color: 'text-orange-500'  },
  load_balancer_dns: { label: 'Load Balancer DNS',    icon: Globe,     color: 'text-emerald-500' },
  vpc_id:            { label: 'VPC ID',               icon: Network,   color: 'text-purple-500'  },
}

function TerraformOutputsTable({ outputs }: { outputs: TerraformOutputs }) {
  const entries = Object.entries(outputs).filter(([, v]) => Boolean(v))
  if (!entries.length) return null

  return (
    <div className={cn(
      'rounded-xl border overflow-hidden',
      'border-orange-200 dark:border-orange-500/20',
      'bg-white dark:bg-surface-900',
    )}>
      <div className={cn(
        'flex items-center gap-2 px-4 py-2.5',
        'bg-gradient-to-r from-orange-50 to-blue-50 dark:from-orange-500/10 dark:to-blue-500/10',
        'border-b border-orange-200 dark:border-orange-500/20',
      )}>
        <span className="text-xs font-semibold text-orange-700 dark:text-orange-300 uppercase tracking-wider">
          Terraform
        </span>
        <div className="flex items-center gap-1">
          <div className="h-0.5 w-6 bg-orange-300 dark:bg-orange-500/50 rounded" />
          <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
          <div className="h-0.5 w-6 bg-blue-300 dark:bg-blue-500/50 rounded" />
        </div>
        <span className="text-xs font-semibold text-blue-700 dark:text-blue-300 uppercase tracking-wider">
          Kubernetes Contract
        </span>
      </div>
      <div className="divide-y divide-slate-100 dark:divide-white/[0.04]">
        {entries.map(([key, val]) => {
          const meta = OUTPUT_META[key as keyof TerraformOutputs]
          const Icon = meta?.icon ?? Server
          return (
            <div key={key} className="flex items-center gap-3 px-4 py-2.5">
              <Icon className={cn('w-3.5 h-3.5 shrink-0', meta?.color ?? 'text-slate-400')} />
              <span className="text-xs font-mono text-slate-500 dark:text-slate-400 w-44 shrink-0 truncate">
                {meta?.label ?? key}
              </span>
              <span className="text-xs font-mono text-slate-700 dark:text-slate-300 truncate">
                {val as string}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── File tabs ─────────────────────────────────────────────────────────────────

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
              ? 'bg-orange-100 dark:bg-orange-500/20 text-orange-700 dark:text-orange-300'
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

// ── Main ──────────────────────────────────────────────────────────────────────

interface Props {
  onApprove: () => void
  onBack: () => void
}

export function TerraformStep({ onApprove, onBack }: Props) {
  const { task, editedArtifacts, editArtifact } = useWorkflowStore()

  const artifacts = task ? getTerraformArtifacts(task) : {}
  const keys = Object.keys(artifacts)
  const [activeKey, setActiveKey] = useState<string>(keys[0] ?? '')

  const editedKeys = new Set(Object.keys(editedArtifacts))

  if (!keys.length) {
    return (
      <StepContainer onBack={onBack} onApprove={onApprove} approveLabel="Continue to Kubernetes">
        <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
          <div className="w-12 h-12 rounded-xl bg-slate-100 dark:bg-surface-800 flex items-center justify-center">
            <Layers className="w-6 h-6 text-slate-400 dark:text-slate-500" />
          </div>
          <div>
            <p className="text-sm font-medium text-slate-600 dark:text-slate-400">No Terraform files found</p>
            <p className="text-xs text-slate-400 dark:text-slate-600 mt-1">No .tf artifacts were generated for this step.</p>
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
          'bg-orange-50 dark:bg-orange-500/10',
          'border border-orange-200 dark:border-orange-500/20',
        )}>
          <Layers className="w-4 h-4 text-orange-600 dark:text-orange-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-orange-800 dark:text-orange-200">
              Terraform Files — {keys.length} file{keys.length > 1 ? 's' : ''} generated
            </p>
            <p className="text-xs text-orange-700/70 dark:text-orange-400/60 mt-0.5">
              Infrastructure as code. Resources, variables, and outputs injected into Kubernetes manifests.
            </p>
          </div>
        </div>

        {/* Terraform outputs contract (if available) */}
        {task?.terraform_outputs && Object.keys(task.terraform_outputs).length > 0 && (
          <TerraformOutputsTable outputs={task.terraform_outputs} />
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
              value={editedArtifacts[activeKey] ?? artifacts[activeKey] ?? ''}
              onChange={(v) => editArtifact(activeKey, v)}
              height="480px"
            />
          )}
        </div>
      </div>
    </StepContainer>
  )
}
