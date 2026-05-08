import { useState } from 'react'
import { Zap, ChevronDown, TrendingDown } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Tip {
  title?: string
  description?: string
  savings?: string | number
  category?: string
  // Some backends send a single string per tip
  [key: string]: unknown
}

interface Props {
  tips: (Tip | string)[]
}

function parseTip(raw: Tip | string, i: number): { title: string; description: string; savings: string | null; category: string } {
  if (typeof raw === 'string') {
    // Try to extract a savings amount from the string: "… save ~$30"
    const savingsMatch = raw.match(/save[s]?\s+[~≈]?\s*\$?([\d,.]+)/i)
    return {
      title: `Optimization ${i + 1}`,
      description: raw,
      savings: savingsMatch ? `$${savingsMatch[1]}` : null,
      category: 'General',
    }
  }
  return {
    title: (raw.title as string) ?? `Tip ${i + 1}`,
    description: (raw.description as string) ?? JSON.stringify(raw),
    savings: raw.savings != null ? String(raw.savings) : null,
    category: (raw.category as string) ?? 'General',
  }
}

const CATEGORY_COLORS: Record<string, string> = {
  'Compute':  'text-blue-400  bg-blue-900/30  border-blue-700/40',
  'Database': 'text-purple-400 bg-purple-900/30 border-purple-700/40',
  'Storage':  'text-green-400  bg-green-900/30  border-green-700/40',
  'Network':  'text-cyan-400   bg-cyan-900/30   border-cyan-700/40',
  'General':  'text-slate-400  bg-slate-800/60  border-slate-700/40',
}

export function OptimizationTipsPanel({ tips }: Props) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set([0]))

  if (!tips || tips.length === 0) return null

  const parsed = tips.map(parseTip)

  function toggle(i: number) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }

  return (
    <div className="space-y-2">
      {parsed.map((tip, i) => {
        const isOpen = expanded.has(i)
        const catColor = CATEGORY_COLORS[tip.category] ?? CATEGORY_COLORS.General

        return (
          <div
            key={i}
            className={cn(
              'rounded-xl border transition-all overflow-hidden',
              isOpen ? 'border-slate-600/80 bg-slate-800/40' : 'border-slate-700/50 bg-slate-800/20',
            )}
          >
            <button
              onClick={() => toggle(i)}
              className="w-full flex items-center justify-between px-4 py-3 text-left"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="p-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20 shrink-0">
                  <Zap className="w-3.5 h-3.5 text-amber-400" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-200 truncate">{tip.title}</p>
                  {!isOpen && (
                    <p className="text-xs text-slate-500 truncate mt-0.5">{tip.description.slice(0, 80)}…</p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0 ml-3">
                {tip.savings && (
                  <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-900/40 border border-green-700/40">
                    <TrendingDown className="w-3 h-3 text-green-400" />
                    <span className="text-[11px] font-semibold text-green-400">save {tip.savings}</span>
                  </div>
                )}
                <span className={cn('text-[10px] px-1.5 py-0.5 rounded border shrink-0', catColor)}>
                  {tip.category}
                </span>
                <ChevronDown className={cn('w-4 h-4 text-slate-500 transition-transform', isOpen && 'rotate-180')} />
              </div>
            </button>

            {isOpen && (
              <div className="px-4 pb-4 pt-1">
                <p className="text-sm text-slate-300 leading-relaxed">{tip.description}</p>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
