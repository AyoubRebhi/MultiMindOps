import { useRef, useState } from 'react'
import { Terminal, Copy, Check, ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  errorExcerpt?: string
  title?: string
  className?: string
}

function copyToClipboard(text: string, onDone: () => void) {
  navigator.clipboard.writeText(text).then(onDone).catch(() => {})
}

// Colorize a single log line based on its content
function lineClass(line: string): string {
  const t = line.toLowerCase()
  if (t.includes('error') || t.startsWith('e ') || t.startsWith('[error]')) return 'text-red-400'
  if (t.includes('warning') || t.startsWith('w '))                           return 'text-yellow-400'
  if (t.startsWith('step ') || t.startsWith('---'))                          return 'text-cyan-400 font-semibold'
  if (t.startsWith('successfully') || t.includes('success'))                 return 'text-emerald-400'
  if (t.startsWith('#') || t.startsWith('=>'))                               return 'text-slate-500'
  if (t.includes('exited') || t.includes('exit code'))                       return 'text-red-500 font-semibold'
  if (t.startsWith('run ') || t.includes('chmod') || t.includes('./mvnw'))  return 'text-blue-300'
  return 'text-slate-300'
}

export function ErrorLogPanel({ errorExcerpt, title = 'Error Excerpt', className }: Props) {
  const [collapsed, setCollapsed]     = useState(false)
  const [copied, setCopied]           = useState(false)
  const containerRef                  = useRef<HTMLDivElement>(null)

  if (!errorExcerpt) return null

  const lines = errorExcerpt.split('\n')

  function handleCopy() {
    copyToClipboard(errorExcerpt!, () => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    })
  }

  return (
    <div className={cn(
      'rounded-xl overflow-hidden border border-slate-700',
      className,
    )}>
      {/* Terminal chrome */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-[#0d1117] border-b border-slate-700/80">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full bg-red-500/80" />
            <span className="w-3 h-3 rounded-full bg-yellow-500/80" />
            <span className="w-3 h-3 rounded-full bg-green-500/80" />
          </div>
          <Terminal className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-xs font-semibold text-slate-200 font-mono tracking-wide">{title}</span>
          <span className="text-[10px] font-mono text-slate-600">{lines.length} lines</span>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            title="Copy to clipboard"
            className={cn(
              'flex items-center gap-1 px-2 py-1 rounded text-[10px] font-mono transition-colors',
              copied
                ? 'text-emerald-400 bg-emerald-900/25'
                : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800',
            )}
          >
            {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
            {copied ? 'Copied' : 'Copy'}
          </button>

          <button
            onClick={() => setCollapsed((c) => !c)}
            className="p-1 rounded text-slate-500 hover:text-slate-300 transition-colors"
            title={collapsed ? 'Expand' : 'Collapse'}
          >
            {collapsed
              ? <ChevronDown className="w-3.5 h-3.5" />
              : <ChevronUp className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div
          ref={containerRef}
          className={cn(
            'overflow-y-auto bg-[#0d1117] px-4 py-3',
            'min-h-[120px] max-h-[360px]',
            'scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent',
          )}
        >
          {lines.map((line, i) => (
            <div
              key={i}
              className={cn(
                'font-mono text-xs leading-5 whitespace-pre-wrap break-all select-text',
                lineClass(line),
              )}
            >
              {/* Line number gutter */}
              <span className="select-none text-slate-700 mr-3 text-[10px]">
                {String(i + 1).padStart(3, ' ')}
              </span>
              {line || ' '}
            </div>
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between px-4 py-1.5 bg-[#0d1117] border-t border-slate-700/60">
        <span className="text-[10px] text-slate-600 font-mono">extracted error context</span>
        <span className="text-[10px] text-red-500 font-mono">✗ build failed</span>
      </div>
    </div>
  )
}
