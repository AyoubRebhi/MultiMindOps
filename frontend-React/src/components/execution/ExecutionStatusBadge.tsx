import { Loader2, CheckCircle2, XCircle, RotateCcw } from 'lucide-react'
import { cn } from '@/lib/utils'

export type ExecutionStatus = 'pending' | 'running' | 'success' | 'failed' | 'retrying'

const CONFIG: Record<ExecutionStatus, {
  label: string
  icon: React.ElementType
  classes: string
}> = {
  pending:  { label: 'Pending',  icon: Loader2,        classes: 'bg-slate-100 text-slate-600 dark:bg-surface-800 dark:text-slate-400' },
  running:  { label: 'Running',  icon: Loader2,        classes: 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300 border border-blue-200 dark:border-blue-500/20' },
  success:  { label: 'Success',  icon: CheckCircle2,   classes: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/20' },
  failed:   { label: 'Failed',   icon: XCircle,        classes: 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300 border border-red-200 dark:border-red-500/20' },
  retrying: { label: 'Retrying', icon: RotateCcw,      classes: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300 border border-amber-200 dark:border-amber-500/20' },
}

interface Props {
  status: ExecutionStatus
  className?: string
}

export function ExecutionStatusBadge({ status, className }: Props) {
  const { label, icon: Icon, classes } = CONFIG[status] ?? CONFIG.pending
  const spin = status === 'running' || status === 'retrying'

  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold',
      classes,
      className,
    )}>
      <Icon className={cn('w-3.5 h-3.5', spin && 'animate-spin')} />
      {label}
    </span>
  )
}
