import { CheckCircle, Circle, Loader2, XCircle, GitBranch, FileCode2, Server, Cloud, Box, ShieldCheck, ClipboardCheck, Workflow } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { LogEntry, PipelineStepStatus, TaskStatus } from '@/types'

interface StepDef {
  id: string
  label: string
  description: string
  icon: React.ElementType
  agentPatterns: string[]
  msgPatterns: string[]
}

const STEPS: StepDef[] = [
  {
    id: 'analysis',
    label: 'Repository Analysis',
    description: 'Scanning codebase',
    icon: GitBranch,
    agentPatterns: ['codebaseanalysis', 'analyze_repository', 'codebase_analysis'],
    msgPatterns: ['analyzing repo', 'repository analysis', 'codebase scan', 'security gate'],
  },
  {
    id: 'planning',
    label: 'Planning',
    description: 'Infrastructure plan',
    icon: ClipboardCheck,
    agentPatterns: ['planneragent', 'multiplanagent', 'costestimation', 'planning_phase'],
    msgPatterns: ['planning', 'generating plan', 'cost estimation', 'plan variant'],
  },
  {
    id: 'docker',
    label: 'Docker',
    description: 'Dockerfile & compose',
    icon: Box,
    agentPatterns: ['infrastructureagent', 'generation_phase', 'docker'],
    msgPatterns: ['dockerfile', 'docker compose', 'docker generation', 'infrastructure agent'],
  },
  {
    id: 'terraform',
    label: 'Terraform',
    description: 'AWS HCL modules',
    icon: Cloud,
    agentPatterns: ['terraformagent', 'terraform_phase'],
    msgPatterns: ['terraform', 'hcl', 'aws provider', 'vpc module'],
  },
  {
    id: 'kubernetes',
    label: 'Kubernetes',
    description: 'K8s manifests',
    icon: Server,
    agentPatterns: ['kubernetesagent', 'kubernetes_phase'],
    msgPatterns: ['kubernetes', 'k8s manifest', 'deployment yaml', 'k8s generation'],
  },
  {
    id: 'security',
    label: 'Security Scan',
    description: 'Security controls',
    icon: ShieldCheck,
    agentPatterns: ['security_scan', 'security_placeholder'],
    msgPatterns: ['security scan', 'security placeholder', 'injecting security'],
  },
  {
    id: 'validation',
    label: 'Validation',
    description: 'Artifact contracts',
    icon: FileCode2,
    agentPatterns: ['validationservice', 'artifactqualityvalidator', 'validation_phase'],
    msgPatterns: ['validat', 'artifact quality', 'contract check'],
  },
  {
    id: 'cicd',
    label: 'CI/CD',
    description: 'Workflow artifacts',
    icon: Workflow,
    agentPatterns: ['cicdagent', 'cicd_phase'],
    msgPatterns: ['ci/cd', 'github actions', 'cicd workflow', 'workflow generation'],
  },
]

function logMatchesStep(log: LogEntry, step: StepDef): boolean {
  const agent = String(log.agent ?? log.step ?? '').toLowerCase()
  const msg   = String(log.message ?? log.step ?? '').toLowerCase()
  return (
    step.agentPatterns.some(p => agent.includes(p) || msg.includes(p)) ||
    step.msgPatterns.some(p => msg.includes(p))
  )
}

function deriveStatus(
  stepIdx: number,
  logs: LogEntry[],
  taskStatus: TaskStatus | string,
): PipelineStepStatus {
  const step = STEPS[stepIdx]
  const stepLogs = logs.filter(l => logMatchesStep(l, step))
  const hasError = stepLogs.some(l => l.level === 'error')

  if (hasError) return 'failed'

  // If a later step has activity, this step is completed
  const laterHasActivity = STEPS.slice(stepIdx + 1).some(later =>
    logs.some(l => logMatchesStep(l, later))
  )

  const isTerminal = ['completed', 'failed', 'human_approved', 'human_approved_with_changes'].includes(taskStatus)

  if (stepLogs.length > 0) {
    if (laterHasActivity || isTerminal) return 'completed'
    return 'running'
  }

  // No logs for this step — check if an earlier step had activity (meaning we haven't reached here yet)
  const earlierHasActivity = STEPS.slice(0, stepIdx).some(earlier =>
    logs.some(l => logMatchesStep(l, earlier))
  )

  if (isTerminal && earlierHasActivity) {
    // Completed task with no logs for this step = skipped/not reached; show as completed to avoid gaps
    // unless a later step also had no activity
    const anyLaterActivity = STEPS.slice(stepIdx).some(s =>
      logs.some(l => logMatchesStep(l, s))
    )
    return anyLaterActivity ? 'completed' : 'pending'
  }

  return 'pending'
}

function StepIcon({ status, Icon }: { status: PipelineStepStatus; Icon: React.ElementType }) {
  switch (status) {
    case 'completed': return <CheckCircle className="w-4 h-4 text-emerald-500" />
    case 'running':   return <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
    case 'failed':    return <XCircle className="w-4 h-4 text-red-500" />
    default:          return <Icon className="w-4 h-4 text-slate-400 dark:text-slate-600" />
  }
}

function statusColor(status: PipelineStepStatus) {
  switch (status) {
    case 'completed': return 'text-emerald-600 dark:text-emerald-400'
    case 'running':   return 'text-blue-600 dark:text-blue-400'
    case 'failed':    return 'text-red-600 dark:text-red-400'
    default:          return 'text-slate-400 dark:text-slate-500'
  }
}

function ConnectorLine({ active }: { active: boolean }) {
  return (
    <div className={cn(
      'hidden sm:block h-0.5 flex-1 mx-1 rounded-full transition-colors',
      active ? 'bg-emerald-400 dark:bg-emerald-600' : 'bg-slate-200 dark:bg-white/[0.06]'
    )} />
  )
}

interface Props {
  logs: LogEntry[]
  taskStatus: TaskStatus | string
}

export function PipelineVisualizer({ logs, taskStatus }: Props) {
  const statuses = STEPS.map((_, i) => deriveStatus(i, logs, taskStatus))
  const completed = statuses.filter(s => s === 'completed').length
  const running = statuses.findIndex(s => s === 'running')

  return (
    <div className={cn(
      'rounded-xl overflow-hidden',
      'bg-white dark:bg-surface-900',
      'border border-slate-200 dark:border-white/[0.06]',
    )}>
      {/* Header */}
      <div className={cn(
        'flex items-center justify-between px-4 py-2.5',
        'bg-slate-50 dark:bg-surface-800/40',
        'border-b border-slate-200 dark:border-white/[0.06]',
      )}>
        <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wider">
          Execution Pipeline
        </span>
        <div className="flex items-center gap-2">
          {running >= 0 && (
            <span className="flex items-center gap-1 text-xs text-blue-500 dark:text-blue-400">
              <Loader2 className="w-3 h-3 animate-spin" />
              {STEPS[running].label}
            </span>
          )}
          <span className="text-xs text-slate-400 dark:text-slate-500 font-mono">
            {completed}/{STEPS.length}
          </span>
        </div>
      </div>

      {/* Step row 1: steps 0–3 */}
      <div className="px-4 pt-4 pb-2">
        <StepRow steps={STEPS.slice(0, 4)} statuses={statuses.slice(0, 4)} />
      </div>

      {/* Vertical connector between rows */}
      <div className="flex justify-end px-4">
        <div className={cn(
          'w-0.5 h-4 rounded-full',
          statuses[3] === 'completed' ? 'bg-emerald-400 dark:bg-emerald-600' : 'bg-slate-200 dark:bg-white/[0.06]'
        )} />
      </div>

      {/* Step row 2: steps 4–7, reversed so flow continues right-to-left visually */}
      <div className="px-4 pt-0 pb-4">
        <StepRow steps={[...STEPS.slice(4, 8)].reverse()} statuses={[...statuses.slice(4, 8)].reverse()} reversed />
      </div>
    </div>
  )
}

function StepRow({
  steps,
  statuses,
  reversed = false,
}: {
  steps: StepDef[]
  statuses: PipelineStepStatus[]
  reversed?: boolean
}) {
  return (
    <div className="flex items-center">
      {steps.map((step, i) => {
        const status = statuses[i]
        // Connector is active if this step and the next are completed
        const connActive = !reversed
          ? status === 'completed' && i < steps.length - 1
          : status === 'completed' && i < steps.length - 1

        return (
          <div key={step.id} className="flex items-center flex-1 min-w-0">
            {/* Step card */}
            <div className="flex flex-col items-center min-w-0 flex-1">
              <div className={cn(
                'flex items-center justify-center w-8 h-8 rounded-full border-2 transition-all',
                status === 'completed' ? 'border-emerald-400 dark:border-emerald-500 bg-emerald-50 dark:bg-emerald-500/10' :
                status === 'running'   ? 'border-blue-400 dark:border-blue-500 bg-blue-50 dark:bg-blue-500/10' :
                status === 'failed'    ? 'border-red-400 dark:border-red-500 bg-red-50 dark:bg-red-500/10' :
                                         'border-slate-200 dark:border-white/[0.08] bg-white dark:bg-surface-900'
              )}>
                <StepIcon status={status} Icon={step.icon} />
              </div>
              <p className={cn('text-[11px] font-medium text-center leading-tight mt-1.5 px-0.5', statusColor(status))}>
                {step.label}
              </p>
              <p className="text-[10px] text-slate-400 dark:text-slate-600 text-center leading-tight hidden md:block">
                {step.description}
              </p>
            </div>

            {/* Connector */}
            {i < steps.length - 1 && <ConnectorLine active={connActive} />}
          </div>
        )
      })}
    </div>
  )
}
