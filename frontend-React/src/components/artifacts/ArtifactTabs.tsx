import { useState } from 'react'
import { Download } from 'lucide-react'
import { CodeViewer } from './CodeViewer'
import { detectLang, cn } from '@/lib/utils'

interface Props {
  artifacts: Record<string, string>
}

function downloadFile(name: string, content: string) {
  const blob = new Blob([content], { type: 'text/plain' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

export function ArtifactTabs({ artifacts }: Props) {
  const keys = Object.keys(artifacts)
  const [active, setActive] = useState(keys[0] ?? '')

  if (!keys.length) return null

  return (
    <div className={cn(
      'rounded-xl overflow-hidden',
      'bg-white dark:bg-surface-900',
      'border border-slate-200 dark:border-white/[0.06]'
    )}>
      {/* Tab bar */}
      <div className={cn(
        'flex items-center gap-1 overflow-x-auto px-3 py-2',
        'bg-slate-50 dark:bg-surface-800/40',
        'border-b border-slate-200 dark:border-white/[0.06]'
      )}>
        {keys.map((k) => (
          <button
            key={k}
            onClick={() => setActive(k)}
            className={cn(
              'px-3 py-1.5 rounded-md text-xs font-mono font-medium whitespace-nowrap transition-colors border',
              active === k
                ? 'bg-brand-50 dark:bg-brand-600/20 text-brand-700 dark:text-brand-300 border-brand-200 dark:border-brand-500/30'
                : cn(
                    'border-transparent',
                    'text-slate-500 dark:text-slate-500',
                    'hover:text-slate-700 dark:hover:text-slate-300',
                    'hover:bg-slate-100 dark:hover:bg-white/[0.04]'
                  )
            )}
          >
            {k}
          </button>
        ))}

        <div className="ml-auto shrink-0">
          <button
            onClick={() => active && downloadFile(active, artifacts[active])}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs border border-transparent transition-colors',
              'text-slate-500 dark:text-slate-500',
              'hover:text-slate-900 dark:hover:text-white',
              'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
              'hover:border-slate-200 dark:hover:border-white/[0.06]'
            )}
          >
            <Download className="w-3.5 h-3.5" />
            Download
          </button>
        </div>
      </div>

      {/* Active file */}
      {active && (
        <CodeViewer
          code={artifacts[active]}
          language={detectLang(active)}
          filename={active}
          showLineNumbers
        />
      )}
    </div>
  )
}
