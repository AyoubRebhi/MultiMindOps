import { cn } from '@/lib/utils'

interface Props {
  className?: string
}

/** Minimal shimmering placeholder. Compose by giving it width/height via className. */
export function Skeleton({ className }: Props) {
  return (
    <div
      className={cn(
        'animate-pulse rounded-md',
        'bg-slate-200/80 dark:bg-white/[0.06]',
        className,
      )}
    />
  )
}

/** Card-shaped skeleton — matches the StatCard layout. */
export function SkeletonStatCard() {
  return (
    <div className={cn(
      'p-5 rounded-xl flex items-center gap-4',
      'bg-white dark:bg-surface-800/40',
      'border border-slate-200 dark:border-white/[0.06]',
    )}>
      <Skeleton className="w-11 h-11" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-6 w-16" />
        <Skeleton className="h-3 w-24" />
      </div>
    </div>
  )
}

/** Table-row skeleton. */
export function SkeletonRow({ cols = 4 }: { cols?: number }) {
  return (
    <tr className="border-b border-slate-100 dark:border-white/[0.04]">
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="py-3 px-4">
          <Skeleton className={cn('h-4', i === 0 ? 'w-3/4' : 'w-1/2')} />
        </td>
      ))}
    </tr>
  )
}
