import { useState } from 'react'
import { diffLines, type Change } from 'diff'
import { cn } from '@/lib/utils'
import type { DiffEntry } from '@/types'

interface Props {
  diffs: Record<string, DiffEntry>
}

function DiffBlock({ before, after }: { before: string; after: string }) {
  const changes: Change[] = diffLines(before, after)

  return (
    <div className="font-mono text-xs overflow-auto">
      {changes.map((part, i) => {
        if (part.added) {
          return (
            <div key={i} className="bg-emerald-500/10 border-l-2 border-emerald-500">
              {part.value.split('\n').filter(Boolean).map((line, j) => (
                <div key={j} className="flex">
                  <span className="w-6 text-emerald-600 text-center select-none px-1">+</span>
                  <span className="text-emerald-300 px-2">{line}</span>
                </div>
              ))}
            </div>
          )
        }
        if (part.removed) {
          return (
            <div key={i} className="bg-red-500/10 border-l-2 border-red-500">
              {part.value.split('\n').filter(Boolean).map((line, j) => (
                <div key={j} className="flex">
                  <span className="w-6 text-red-600 text-center select-none px-1">-</span>
                  <span className="text-red-300 line-through px-2">{line}</span>
                </div>
              ))}
            </div>
          )
        }
        // unchanged — show max 3 lines of context
        const lines = part.value.split('\n').filter(Boolean)
        const ctx = lines.length > 6 ? [...lines.slice(0, 3), null, ...lines.slice(-3)] : lines
        return (
          <div key={i}>
            {ctx.map((line, j) =>
              line === null ? (
                <div key={j} className="text-slate-600 px-2 py-0.5 select-none text-center">
                  ⋯
                </div>
              ) : (
                <div key={j} className="flex">
                  <span className="w-6 text-slate-700 text-center select-none px-1"> </span>
                  <span className="text-slate-500 px-2">{line}</span>
                </div>
              )
            )}
          </div>
        )
      })}
    </div>
  )
}

export function DiffViewer({ diffs }: Props) {
  const keys = Object.keys(diffs)
  const [active, setActive] = useState(keys[0] ?? '')

  if (!keys.length) return null

  const entry = diffs[active]

  return (
    <div className="rounded-xl border border-white/[0.06] overflow-hidden bg-surface-900">
      {/* Tab bar */}
      <div className="flex items-center gap-1 overflow-x-auto border-b border-white/[0.06] bg-surface-800/40 px-3 py-2">
        {keys.map((k) => (
          <button
            key={k}
            onClick={() => setActive(k)}
            className={cn(
              'px-3 py-1.5 rounded-md text-xs font-mono font-medium whitespace-nowrap transition-colors',
              active === k
                ? 'bg-brand-600/20 text-brand-300 border border-brand-500/30'
                : 'text-slate-500 hover:text-slate-300 border border-transparent'
            )}
          >
            {k}
            {diffs[k].changes !== undefined && (
              <span className="ml-1.5 text-xs text-slate-600">
                ±{diffs[k].changes}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Diff */}
      {entry && entry.before !== undefined && entry.after !== undefined && (
        <div className="p-4 bg-surface-950 overflow-auto max-h-[500px]">
          <DiffBlock before={entry.before} after={entry.after} />
        </div>
      )}
    </div>
  )
}
