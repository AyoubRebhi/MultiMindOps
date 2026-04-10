import { useState } from 'react'
import { Download } from 'lucide-react'
import { CodeViewer } from './CodeViewer'
import { detectLang } from '@/lib/utils'

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
    <div className="rounded-xl border border-white/[0.06] overflow-hidden bg-surface-900">
      {/* Tab bar */}
      <div className="flex items-center gap-1 overflow-x-auto border-b border-white/[0.06] bg-surface-800/40 px-3 py-2">
        {keys.map((k) => (
          <button
            key={k}
            onClick={() => setActive(k)}
            className={`px-3 py-1.5 rounded-md text-xs font-mono font-medium whitespace-nowrap transition-colors ${
              active === k
                ? 'bg-brand-600/20 text-brand-300 border border-brand-500/30'
                : 'text-slate-500 hover:text-slate-300 border border-transparent hover:bg-white/[0.04]'
            }`}
          >
            {k}
          </button>
        ))}

        {/* Spacer + download */}
        <div className="ml-auto shrink-0">
          <button
            onClick={() => active && downloadFile(active, artifacts[active])}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-slate-500 hover:text-white transition-colors hover:bg-white/[0.05] border border-transparent hover:border-white/[0.06]"
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
