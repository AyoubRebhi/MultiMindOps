import { AlertTriangle, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  title?: string
  message: string
  onDismiss?: () => void
  className?: string
}

export function ErrorAlert({ title = 'Error', message, onDismiss, className }: Props) {
  return (
    <div
      className={cn(
        'flex items-start gap-3 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400',
        className
      )}
    >
      <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs mt-0.5 text-red-400/80 break-words">{message}</p>
      </div>
      {onDismiss && (
        <button onClick={onDismiss} className="shrink-0 hover:text-red-300 transition-colors">
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  )
}
