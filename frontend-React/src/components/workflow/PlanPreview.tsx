import { useState } from 'react'
import {
  CheckSquare,
  Square,
  ChevronRight,
  FileCode,
  Layers,
  GitBranch,
  Shield,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PlanPreviewResponse } from '@/types'
import { SecurityScore } from '@/components/security/SecurityScore'

interface Props {
  preview: PlanPreviewResponse
  onApprove: (approvedArtifacts: string[]) => void
  onBack: () => void
  isLoading?: boolean
}

const ARTIFACT_ICONS: Record<string, React.ElementType> = {
  dockerfile:     FileCode,
  docker_compose: Layers,
  kubernetes:     Layers,
  k8s:            Layers,
  terraform:      Layers,
  github_actions: GitBranch,
  ci:             GitBranch,
  cicd:           GitBranch,
}

function artifactIcon(name: string) {
  const lower = name.toLowerCase()
  for (const [key, Icon] of Object.entries(ARTIFACT_ICONS)) {
    if (lower.includes(key)) return Icon
  }
  return FileCode
}

export function PlanPreview({ preview, onApprove, onBack, isLoading }: Props) {
  const artifacts: string[] = preview.plan?.artifacts ?? []
  const [selected, setSelected] = useState<Set<string>>(new Set(artifacts))

  const toggle = (art: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(art) ? next.delete(art) : next.add(art)
      return next
    })

  const toggleAll = () =>
    setSelected(selected.size === artifacts.length ? new Set() : new Set(artifacts))

  return (
    <div className="space-y-6 animate-slide-in">
      {/* Plan summary */}
      {preview.plan?.summary && (
        <div className={cn(
          'p-4 rounded-lg',
          'bg-brand-50 dark:bg-brand-600/10',
          'border border-brand-200 dark:border-brand-500/20'
        )}>
          <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
            {preview.plan.summary}
          </p>
        </div>
      )}

      {/* Repo security */}
      {preview.repository_security && (
        <SecurityScore security={preview.repository_security} compact />
      )}

      {/* Actions list */}
      {preview.plan?.actions && preview.plan.actions.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-slate-600 dark:text-slate-400 mb-3">
            Planned steps
          </h3>
          <div className="space-y-2">
            {preview.plan.actions.map((action, i) => (
              <div
                key={i}
                className={cn(
                  'flex items-start gap-3 p-3 rounded-lg',
                  'bg-slate-50 dark:bg-surface-800/50',
                  'border border-slate-100 dark:border-white/[0.04]'
                )}
              >
                <div className={cn(
                  'w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5',
                  'bg-brand-50 dark:bg-brand-600/20',
                  'border border-brand-200 dark:border-brand-500/30'
                )}>
                  <span className="text-xs text-brand-600 dark:text-brand-400 font-mono">{i + 1}</span>
                </div>
                <div className="min-w-0">
                  {action.agent && (
                    <span className="text-xs text-brand-600 dark:text-brand-400 font-medium">
                      [{String(action.agent)}]{'  '}
                    </span>
                  )}
                  <span className="text-sm text-slate-700 dark:text-slate-300">
                    {String(action.description ?? action.type ?? '')}
                  </span>
                </div>
                <ChevronRight className="w-4 h-4 text-slate-300 dark:text-slate-600 shrink-0 mt-0.5" />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Artifact selection */}
      {artifacts.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-slate-600 dark:text-slate-400">
              Artifacts to generate
            </h3>
            <button
              onClick={toggleAll}
              className="text-xs text-brand-600 dark:text-brand-400 hover:text-brand-500 dark:hover:text-brand-300 transition-colors"
            >
              {selected.size === artifacts.length ? 'Deselect all' : 'Select all'}
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {artifacts.map((art) => {
              const Icon = artifactIcon(art)
              const isSelected = selected.has(art)
              return (
                <button
                  key={art}
                  onClick={() => toggle(art)}
                  className={cn(
                    'flex items-center gap-3 p-3 rounded-lg border text-left transition-all',
                    isSelected
                      ? 'bg-brand-50 dark:bg-brand-600/10 border-brand-200 dark:border-brand-500/30 text-slate-900 dark:text-white'
                      : cn(
                          'bg-white dark:bg-surface-800/40',
                          'border-slate-200 dark:border-white/[0.05]',
                          'text-slate-500 dark:text-slate-400',
                          'hover:border-slate-300 dark:hover:border-white/10'
                        )
                  )}
                >
                  {isSelected
                    ? <CheckSquare className="w-4 h-4 text-brand-600 dark:text-brand-400 shrink-0" />
                    : <Square      className="w-4 h-4 shrink-0" />}
                  <Icon className="w-4 h-4 shrink-0" />
                  <span className="text-sm font-medium truncate">{art}</span>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Technologies */}
      {preview.plan?.technologies && (
        <div className="flex flex-wrap gap-2">
          {(preview.plan.technologies as string[]).map((t) => (
            <span
              key={t}
              className={cn(
                'px-2 py-0.5 rounded text-xs font-mono',
                'text-slate-500 dark:text-slate-400',
                'bg-slate-100 dark:bg-white/[0.04]',
                'border border-slate-200 dark:border-white/[0.06]'
              )}
            >
              {t}
            </span>
          ))}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-3 pt-2">
        <button
          onClick={onBack}
          disabled={isLoading}
          className={cn(
            'px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-40',
            'border border-slate-200 dark:border-white/[0.08]',
            'text-slate-600 dark:text-slate-400',
            'hover:text-slate-900 dark:hover:text-white',
            'hover:border-slate-300 dark:hover:border-white/20',
            'hover:bg-slate-50 dark:hover:bg-white/[0.03]'
          )}
        >
          Back
        </button>
        <button
          onClick={() => onApprove([...selected])}
          disabled={isLoading || selected.size === 0}
          className="flex items-center gap-2 px-6 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isLoading ? (
            <>
              <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Generating…
            </>
          ) : (
            <>
              <Shield className="w-4 h-4" />
              Generate artifacts ({selected.size})
            </>
          )}
        </button>
      </div>
    </div>
  )
}
