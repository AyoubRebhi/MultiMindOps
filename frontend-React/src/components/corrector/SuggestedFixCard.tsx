import { useState } from 'react'
import { ChevronDown, ChevronRight, Copy, Check, Wrench, FileCode } from 'lucide-react'
import { cn } from '@/lib/utils'
import { severityMeta } from '@/lib/utils'
import type { CorrectorFix } from '@/services/correctorApi'

// ── Diff line renderer ────────────────────────────────────────────────────────

type DiffLine = { type: 'add' | 'remove' | 'context' | 'header'; content: string }

function parseDiff(patch: string): DiffLine[] {
  return patch.split('\n').map((line): DiffLine => {
    if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('@@'))
      return { type: 'header', content: line }
    if (line.startsWith('+'))  return { type: 'add',     content: line }
    if (line.startsWith('-'))  return { type: 'remove',  content: line }
    return { type: 'context', content: line }
  })
}

function DiffViewer({ patch }: { patch: string }) {
  const [copied, setCopied] = useState(false)
  const lines = parseDiff(patch)

  function handleCopy() {
    navigator.clipboard.writeText(patch).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    }).catch(() => {})
  }

  return (
    <div className="rounded-lg overflow-hidden border border-slate-700">
      {/* Diff toolbar */}
      <div className="flex items-center justify-between px-3 py-2 bg-[#0d1117] border-b border-slate-700/60">
        <div className="flex items-center gap-2">
          <FileCode className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-[10px] font-mono text-slate-500 uppercase tracking-widest">patch</span>
        </div>
        <button
          onClick={handleCopy}
          className={cn(
            'flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-colors',
            copied
              ? 'text-emerald-400 bg-emerald-900/20'
              : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800',
          )}
        >
          {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
          {copied ? 'Copied' : 'Copy patch'}
        </button>
      </div>

      {/* Diff lines */}
      <div className="overflow-x-auto bg-[#0d1117] max-h-[280px] overflow-y-auto">
        {lines.map((line, i) => (
          <div
            key={i}
            className={cn(
              'flex font-mono text-xs leading-5 select-text',
              line.type === 'add'     && 'bg-emerald-900/20',
              line.type === 'remove'  && 'bg-red-900/20',
              line.type === 'header'  && 'bg-blue-900/10',
              line.type === 'context' && '',
            )}
          >
            {/* Gutter */}
            <span className={cn(
              'shrink-0 w-7 text-center text-[10px] border-r select-none py-0.5',
              line.type === 'add'    && 'text-emerald-600 border-emerald-800/40 bg-emerald-900/30',
              line.type === 'remove' && 'text-red-600 border-red-800/40 bg-red-900/30',
              line.type === 'header' && 'text-blue-600 border-blue-800/40 bg-blue-900/20',
              line.type === 'context'&& 'text-slate-700 border-slate-800',
            )}>
              {line.type === 'add'    ? '+' : ''}
              {line.type === 'remove' ? '−' : ''}
              {line.type === 'header' ? '~' : ''}
              {line.type === 'context'? ' ' : ''}
            </span>

            {/* Content */}
            <span className={cn(
              'flex-1 px-3 py-0.5 whitespace-pre break-all',
              line.type === 'add'    && 'text-emerald-300',
              line.type === 'remove' && 'text-red-300',
              line.type === 'header' && 'text-blue-400',
              line.type === 'context'&& 'text-slate-400',
            )}>
              {line.content || ' '}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Severity badge ─────────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: string }) {
  const meta = severityMeta(severity)
  return (
    <span className={cn(
      'inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border',
      meta.color,
    )}>
      {meta.label}
    </span>
  )
}

// ── Main card ─────────────────────────────────────────────────────────────────

interface Props {
  fix: CorrectorFix
  index: number
  defaultOpen?: boolean
}

export function SuggestedFixCard({ fix, index, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className={cn(
      'rounded-xl border overflow-hidden transition-all',
      open
        ? 'border-slate-600 bg-[#0d1117]'
        : 'border-slate-700/60 bg-[#0a0d14] hover:border-slate-600',
    )}>
      {/* Card header — always visible */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-3 px-5 py-4 text-left transition-colors hover:bg-white/[0.02]"
      >
        {/* Index badge */}
        <div className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center bg-slate-800 border border-slate-600 text-xs font-bold text-slate-300 font-mono">
          {index + 1}
        </div>

        {/* Wrench icon */}
        <Wrench className="w-4 h-4 text-amber-400 shrink-0" />

        {/* Title + meta */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-slate-100 leading-tight truncate">{fix.title}</p>
          <div className="flex items-center gap-2 mt-1">
            <SeverityBadge severity={fix.severity} />
            <span className="text-[10px] text-slate-500 font-mono">→ {fix.applies_to}</span>
          </div>
        </div>

        {open
          ? <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />
          : <ChevronRight className="w-4 h-4 text-slate-500 shrink-0" />}
      </button>

      {/* Expanded body */}
      {open && (
        <div className="px-5 pb-5 space-y-4 border-t border-slate-700/60">
          {/* Explanation */}
          <div className="pt-4">
            <p className="text-[10px] uppercase tracking-widest text-slate-500 font-medium mb-2">
              Explanation
            </p>
            <p className="text-sm text-slate-300 leading-relaxed">{fix.explanation}</p>
          </div>

          {/* File target */}
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/60 border border-slate-700/60">
            <FileCode className="w-3.5 h-3.5 text-slate-400 shrink-0" />
            <span className="text-xs font-mono text-slate-300">{fix.applies_to}</span>
            <span className="text-[10px] text-slate-600 ml-auto">target file</span>
          </div>

          {/* Patch diff */}
          {fix.patch && (
            <div>
              <p className="text-[10px] uppercase tracking-widest text-slate-500 font-medium mb-2">
                Proposed Change
              </p>
              <DiffViewer patch={fix.patch} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
