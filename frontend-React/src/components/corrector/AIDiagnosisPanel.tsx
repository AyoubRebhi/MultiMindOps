import { Brain, Zap, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { CorrectorAnalysis } from '@/services/correctorApi'

interface Props {
  analysis: CorrectorAnalysis
  isRunning?: boolean
}

export function AIDiagnosisPanel({ analysis, isRunning = false }: Props) {
  const hasContent = analysis.root_cause || analysis.error_type

  return (
    <div className={cn(
      'rounded-xl border overflow-hidden',
      'border-purple-500/20 bg-gradient-to-br from-[#0d0f1a] to-[#0d1117]',
    )}>
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-3.5 border-b border-purple-500/15 bg-purple-500/5">
        <div className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center bg-purple-500/15 border border-purple-500/25">
          <Brain className="w-4 h-4 text-purple-400" />
        </div>
        <div>
          <p className="text-sm font-semibold text-purple-200">AI Incident Analysis</p>
          <p className="text-xs text-purple-400/60">
            {isRunning
              ? 'Corrector agent is analyzing the build failure…'
              : 'Autonomous diagnosis by DockerCorrectorAgent'}
          </p>
        </div>

        {isRunning && (
          <div className="ml-auto flex items-center gap-2">
            <span className="flex items-center gap-1.5 text-xs text-purple-300 font-mono animate-pulse">
              <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" />
              analyzing
            </span>
          </div>
        )}
      </div>

      {/* Body */}
      <div className="px-5 py-4 space-y-4">
        {isRunning && !hasContent && (
          <div className="space-y-3">
            {['w-3/4', 'w-full', 'w-5/6', 'w-2/3'].map((w, i) => (
              <div key={i} className={cn('h-3 rounded bg-purple-500/10 animate-pulse', w)} />
            ))}
          </div>
        )}

        {!isRunning && !hasContent && (
          <div className="flex items-center gap-2 text-slate-500 text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>No AI diagnosis available — run analysis again.</span>
          </div>
        )}

        {analysis.error_type && (
          <div className="flex items-start gap-3">
            <Zap className="w-4 h-4 text-purple-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-[10px] uppercase tracking-widest text-purple-500/70 font-medium mb-1">
                Identified Failure Pattern
              </p>
              <span className={cn(
                'inline-flex items-center px-2.5 py-1 rounded-md text-xs font-semibold font-mono',
                'bg-purple-500/10 border border-purple-500/25 text-purple-300',
              )}>
                {analysis.error_type.replace(/_/g, ' ')}
              </span>
            </div>
          </div>
        )}

        {analysis.root_cause && (
          <div className="rounded-lg border border-purple-500/15 bg-purple-500/5 p-4">
            <p className="text-[10px] uppercase tracking-widest text-purple-500/70 font-medium mb-2">
              Root Cause Analysis
            </p>
            <p className="text-sm text-slate-300 leading-relaxed">{analysis.root_cause}</p>
          </div>
        )}

        {analysis.retry_recommended != null && (
          <div className={cn(
            'flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border',
            analysis.retry_recommended
              ? 'bg-emerald-500/8 border-emerald-500/20 text-emerald-400'
              : 'bg-slate-700/30 border-slate-600/30 text-slate-400',
          )}>
            <span>{analysis.retry_recommended ? '✓' : '✗'}</span>
            <span>
              {analysis.retry_recommended
                ? 'Automated retry is recommended — apply the suggested fix below'
                : 'Automated retry not recommended — manual review required'}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
