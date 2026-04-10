import { useState } from 'react'
import { CheckCircle, Edit3 } from 'lucide-react'
import { CodeViewer } from '@/components/artifacts/CodeViewer'
import { detectLang, cn } from '@/lib/utils'
import type { TaskResponse } from '@/types'

interface Props {
  task: TaskResponse
  onSubmitReview: (reviewed: Record<string, string>, notes: string) => void
  isLoading?: boolean
}

export function ArtifactReview({ task, onSubmitReview, isLoading }: Props) {
  const rawArtifacts: Record<string, string> =
    (task.result?.artifacts as Record<string, string>) ?? {}

  const [artifacts, setArtifacts] = useState<Record<string, string>>(rawArtifacts)
  const [activeTab, setActiveTab] = useState(Object.keys(rawArtifacts)[0] ?? '')
  const [editMode, setEditMode]   = useState(false)
  const [notes, setNotes]         = useState('')

  const keys = Object.keys(artifacts)

  return (
    <div className="space-y-4 animate-slide-in">
      <div className={cn(
        'p-4 rounded-lg',
        'bg-amber-50 dark:bg-amber-500/10',
        'border border-amber-200 dark:border-amber-500/20'
      )}>
        <p className="text-sm text-amber-700 dark:text-amber-300 font-medium">
          Human review required
        </p>
        <p className="text-xs text-amber-600/80 dark:text-amber-400/70 mt-1">
          Review and optionally edit the generated artifacts before approving.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 overflow-x-auto pb-1">
        {keys.map((k) => (
          <button
            key={k}
            onClick={() => { setActiveTab(k); setEditMode(false) }}
            className={cn(
              'px-3 py-1.5 rounded-md text-xs font-mono font-medium whitespace-nowrap transition-colors border',
              activeTab === k
                ? 'bg-brand-50 dark:bg-brand-600/20 text-brand-700 dark:text-brand-300 border-brand-200 dark:border-brand-500/30'
                : 'border-transparent text-slate-500 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
            )}
          >
            {k}
          </button>
        ))}
      </div>

      {/* Code area */}
      {activeTab && (
        <div className={cn(
          'rounded-lg overflow-hidden',
          'border border-slate-200 dark:border-white/[0.06]'
        )}>
          <div className={cn(
            'flex items-center justify-between px-4 py-2',
            'bg-slate-50 dark:bg-surface-800/50',
            'border-b border-slate-100 dark:border-white/[0.04]'
          )}>
            <span className="text-xs font-mono text-slate-500 dark:text-slate-400">{activeTab}</span>
            <button
              onClick={() => setEditMode((v) => !v)}
              className="flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors"
            >
              <Edit3 className="w-3.5 h-3.5" />
              {editMode ? 'Preview' : 'Edit'}
            </button>
          </div>

          {editMode ? (
            <textarea
              value={artifacts[activeTab]}
              onChange={(e) =>
                setArtifacts((prev) => ({ ...prev, [activeTab]: e.target.value }))
              }
              className={cn(
                'w-full font-mono text-xs p-4 resize-none focus:outline-none',
                'bg-white dark:bg-surface-950',
                'text-slate-800 dark:text-slate-200'
              )}
              style={{ minHeight: '400px' }}
              spellCheck={false}
            />
          ) : (
            <CodeViewer
              code={artifacts[activeTab]}
              language={detectLang(activeTab)}
              filename={activeTab}
              maxHeight="400px"
            />
          )}
        </div>
      )}

      {/* Review notes */}
      <div>
        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
          Review notes{' '}
          <span className="text-slate-400 dark:text-slate-600">(optional)</span>
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Add any notes or feedback for the AI agents…"
          className={cn(
            'w-full rounded-lg px-3 py-2 text-sm resize-none focus:outline-none transition-colors',
            'bg-white dark:bg-surface-800/50',
            'border border-slate-200 dark:border-white/[0.06]',
            'text-slate-800 dark:text-slate-300',
            'placeholder-slate-400 dark:placeholder-slate-600',
            'focus:border-brand-400 dark:focus:border-brand-500/40'
          )}
          rows={3}
        />
      </div>

      {/* Submit */}
      <button
        onClick={() => onSubmitReview(artifacts, notes)}
        disabled={isLoading}
        className="flex items-center gap-2 px-6 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition-colors disabled:opacity-40"
      >
        {isLoading ? (
          <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
        ) : (
          <CheckCircle className="w-4 h-4" />
        )}
        Approve & Finalize
      </button>
    </div>
  )
}
