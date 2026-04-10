import { cn } from '@/lib/utils'

export function LoadingSpinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn('animate-spin text-brand-500 dark:text-brand-400', className ?? 'w-5 h-5')}
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  )
}

export function PageLoader() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 py-24">
      <LoadingSpinner className="w-8 h-8" />
      <p className="text-sm text-slate-500 dark:text-slate-500">Loading…</p>
    </div>
  )
}
