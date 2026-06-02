import { useMemo, useState } from 'react'
import { Copy, Check, FileCode } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  files: Record<string, string>
  className?: string
  title?: string
  subtitle?: string
}

const PREFERRED_ORDER = [
  'providers.tf',
  'main.tf',
  'variables.tf',
  'terraform.tfvars',
  'outputs.tf',
  'backend.tf',
]

function orderFiles(filenames: string[]): string[] {
  const known = PREFERRED_ORDER.filter((f) => filenames.includes(f))
  const extras = filenames.filter((f) => !PREFERRED_ORDER.includes(f)).sort()
  return [...known, ...extras]
}

export function ArtifactViewer({ files, className, title, subtitle }: Props) {
  const keys = useMemo(() => orderFiles(Object.keys(files)), [files])
  const [active, setActive] = useState<string>(keys[0] ?? '')
  const [copied, setCopied] = useState(false)

  const currentKey = keys.includes(active) ? active : keys[0] ?? ''
  const content = currentKey ? files[currentKey] ?? '' : ''

  const handleCopy = async () => {
    if (!content) return
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable — silently ignore */
    }
  }

  if (!keys.length) {
    return (
      <div className={cn(
        'flex flex-col items-center justify-center gap-3 py-16 text-center rounded-xl border',
        'bg-white dark:bg-surface-900',
        'border-slate-200 dark:border-white/[0.06]',
        className,
      )}>
        <div className="w-12 h-12 rounded-xl bg-slate-100 dark:bg-surface-800 flex items-center justify-center">
          <FileCode className="w-6 h-6 text-slate-400 dark:text-slate-500" />
        </div>
        <p className="text-sm font-medium text-slate-600 dark:text-slate-400">No Terraform files</p>
      </div>
    )
  }

  return (
    <div className={cn(
      'rounded-xl border overflow-hidden',
      'bg-white dark:bg-surface-900',
      'border-slate-200 dark:border-white/[0.06]',
      className,
    )}>
      {(title || subtitle) && (
        <div className="px-4 py-3 border-b border-slate-200 dark:border-white/[0.06] bg-slate-50/60 dark:bg-surface-800/30">
          {title && (
            <p className="text-sm font-medium text-slate-700 dark:text-slate-200">{title}</p>
          )}
          {subtitle && (
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{subtitle}</p>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-1 px-4 py-3 border-b border-slate-200 dark:border-white/[0.06] bg-slate-50 dark:bg-surface-800/30">
        {keys.map((k) => (
          <button
            key={k}
            onClick={() => setActive(k)}
            className={cn(
              'px-2.5 py-1 rounded-lg text-xs font-mono font-medium transition-colors',
              currentKey === k
                ? 'bg-orange-100 dark:bg-orange-500/20 text-orange-700 dark:text-orange-300'
                : 'text-slate-500 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/[0.05]',
            )}
          >
            {k}
          </button>
        ))}
      </div>

      <div className="relative">
        <button
          onClick={handleCopy}
          className={cn(
            'absolute top-2 right-2 z-10 flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors',
            'bg-white/90 dark:bg-surface-900/80 backdrop-blur-sm',
            'border border-slate-200 dark:border-white/[0.08]',
            'text-slate-600 dark:text-slate-300',
            'hover:bg-slate-50 dark:hover:bg-surface-800',
          )}
          title="Copy to clipboard"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-500" />
              Copied
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              Copy
            </>
          )}
        </button>
        <pre className={cn(
          'overflow-auto text-xs font-mono leading-relaxed px-4 py-4',
          'text-slate-800 dark:text-slate-200',
          'bg-slate-50/50 dark:bg-surface-950',
          'max-h-[520px]',
        )}>
          <code>{content}</code>
        </pre>
      </div>
    </div>
  )
}
