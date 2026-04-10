import { cn, statusMeta } from '@/lib/utils'
import type { TaskStatus } from '@/types'

interface Props {
  status: TaskStatus
  size?: 'sm' | 'md'
}

export function StatusBadge({ status, size = 'md' }: Props) {
  const { label, color, dot, pulse } = statusMeta(status)

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border font-medium',
        color,
        size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs'
      )}
    >
      <span className={cn('w-1.5 h-1.5 rounded-full', dot, pulse && 'animate-pulse')} />
      {label}
    </span>
  )
}
