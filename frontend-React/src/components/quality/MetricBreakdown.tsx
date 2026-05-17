import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { cn, scoreColor } from '@/lib/utils'

export interface MetricItem {
  key: string
  label: string
  score: number
  feedback: string
  icon: React.ElementType
}

interface Props {
  metrics: MetricItem[]
}

function MetricRow({ label, score, feedback, icon: Icon }: Omit<MetricItem, 'key'>) {
  const [open, setOpen] = useState(false)
  const color = scoreColor(score)

  const barBg =
    score >= 80
      ? 'bg-emerald-100 dark:bg-emerald-500/10'
      : score >= 60
      ? 'bg-amber-100 dark:bg-amber-500/10'
      : 'bg-red-100 dark:bg-red-500/10'

  return (
    <div className={cn('rounded-lg border transition-colors', barBg, 'border-transparent')}>
      <button
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left group"
        onClick={() => setOpen((o) => !o)}
      >
        <Icon className="w-4 h-4 shrink-0 text-slate-400 dark:text-slate-500" />
        <span className="flex-1 text-xs font-medium text-slate-700 dark:text-slate-300">
          {label}
        </span>
        <span className="text-sm font-bold tabular-nums mr-1" style={{ color }}>
          {score}
        </span>
        {open
          ? <ChevronUp className="w-3 h-3 text-slate-400 shrink-0" />
          : <ChevronDown className="w-3 h-3 text-slate-400 shrink-0" />}
      </button>

      {/* Progress bar */}
      <div className="mx-3 mb-2 h-1 rounded-full bg-slate-200 dark:bg-surface-700">
        <div
          className="h-1 rounded-full transition-all duration-700"
          style={{ width: `${score}%`, backgroundColor: color }}
        />
      </div>

      {/* Collapsible feedback */}
      {open && (
        <p className="px-3 pb-3 text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
          {feedback}
        </p>
      )}
    </div>
  )
}

export function MetricBreakdown({ metrics }: Props) {
  return (
    <div className="space-y-2">
      {metrics.map(({ key, ...metric }) => (
        <MetricRow key={key} {...metric} />
      ))}
    </div>
  )
}
