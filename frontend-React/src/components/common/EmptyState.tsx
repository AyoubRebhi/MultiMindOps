import { type ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface Props {
  icon?: React.ElementType
  title: string
  description?: string
  action?: ReactNode
  className?: string
}

export function EmptyState({ icon: Icon, title, description, action, className }: Props) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center py-14 px-6 text-center rounded-xl',
        'border border-dashed border-slate-200 dark:border-white/[0.08]',
        'bg-white/40 dark:bg-surface-900/40',
        className,
      )}
    >
      {Icon && (
        <div className="w-10 h-10 rounded-lg bg-slate-100 dark:bg-white/[0.04] flex items-center justify-center mb-3">
          <Icon className="w-5 h-5 text-slate-400 dark:text-slate-500" />
        </div>
      )}
      <p className="text-sm font-medium text-slate-700 dark:text-slate-200">{title}</p>
      {description && (
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-500 max-w-sm">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}
