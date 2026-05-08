import { useState } from 'react'
import { Info, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  assumptions: (string | Record<string, unknown>)[]
}

function parseAssumption(raw: string | Record<string, unknown>): string {
  if (typeof raw === 'string') return raw
  const { title, description, value, note, ...rest } = raw as Record<string, string>
  if (title && description) return `${title}: ${description}`
  if (title && value)       return `${title}: ${value}`
  if (note)                 return note
  return JSON.stringify(rest || raw)
}

export function AssumptionsPanel({ assumptions }: Props) {
  const [open, setOpen] = useState(false)

  if (!assumptions || assumptions.length === 0) return null

  const items = assumptions.map(parseAssumption)

  return (
    <div className={cn(
      'rounded-xl border overflow-hidden transition-all',
      open ? 'border-slate-600/80' : 'border-slate-700/50',
    )}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 bg-slate-800/40 hover:bg-slate-800/60 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <Info className="w-4 h-4 text-slate-400 shrink-0" />
          <span className="text-sm font-medium text-slate-300">Pricing Assumptions</span>
          <span className="text-[11px] text-slate-500 bg-slate-700/60 px-1.5 py-0.5 rounded font-mono">
            {items.length}
          </span>
        </div>
        <ChevronDown className={cn('w-4 h-4 text-slate-500 transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <ul className="divide-y divide-slate-800/60 bg-slate-900/40">
          {items.map((item, i) => (
            <li key={i} className="flex items-start gap-3 px-4 py-2.5">
              <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-slate-600 shrink-0" />
              <p className="text-xs text-slate-400 leading-relaxed">{item}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
