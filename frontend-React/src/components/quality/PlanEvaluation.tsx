import { useEffect, useRef, useState } from 'react'
import { RadialBarChart, RadialBar, ResponsiveContainer } from 'recharts'
import { ClipboardList, AlignLeft, Bot, ShieldCheck, Loader2, RefreshCw } from 'lucide-react'
import { cn, scoreColor, scoreGrade } from '@/lib/utils'
import { useThemeStore } from '@/store/themeStore'
import { judgePlan } from '@/api/evaluation'
import { MetricBreakdown } from './MetricBreakdown'
import type { PlanJudgeResponse } from '@/api/evaluation'
import type { PlanData } from '@/types'

interface Props {
  plan: PlanData
  originalPrompt: string
  repositoryContext?: Record<string, unknown>
  /** Auto-trigger evaluation on mount */
  autoRun?: boolean
}

const METRIC_CONFIG = [
  { key: 'completeness',    label: 'Completeness',    icon: ClipboardList },
  { key: 'clarity',         label: 'Clarity',          icon: AlignLeft     },
  { key: 'agent_readiness', label: 'Agent-Readiness',  icon: Bot           },
  { key: 'security_fit',    label: 'Security Fit',     icon: ShieldCheck   },
] as const

export function PlanEvaluation({
  plan,
  originalPrompt,
  repositoryContext,
  autoRun = false,
}: Props) {
  const isDark = useThemeStore((s) => s.theme === 'dark')
  const [result, setResult] = useState<PlanJudgeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ranRef = useRef(false)

  const run = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await judgePlan({
        plan_dict: plan as Record<string, unknown>,
        original_prompt: originalPrompt,
        context: repositoryContext,
      })
      setResult(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Plan evaluation failed')
    } finally {
      setLoading(false)
    }
  }

  // Auto-run once on mount
  useEffect(() => {
    if (autoRun && !ranRef.current) {
      ranRef.current = true
      run()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const score = result?.global_score ?? 0
  const color = scoreColor(score)
  const grade = scoreGrade(score)
  const trackColor = isDark ? '#1e293b' : '#e2e8f0'

  const metrics = result
    ? METRIC_CONFIG.map(({ key, label, icon }) => ({
        key,
        label,
        icon,
        score: result.metrics[key]?.score ?? 0,
        feedback: result.metrics[key]?.feedback ?? '',
      }))
    : []

  // Determine panel border based on score
  const panelBorder =
    !result
      ? 'border-slate-200 dark:border-white/[0.06]'
      : score >= 75
      ? 'border-emerald-200 dark:border-emerald-500/20'
      : score >= 50
      ? 'border-amber-200 dark:border-amber-500/20'
      : 'border-red-200 dark:border-red-500/20'

  return (
    <div
      className={cn(
        'rounded-xl p-5 space-y-4',
        'bg-white dark:bg-surface-800/40',
        'border',
        panelBorder,
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
            Plan Quality
          </h3>
          {!result && !loading && (
            <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
              Evaluate plan with LLM-as-a-Judge
            </p>
          )}
        </div>
        <button
          onClick={run}
          disabled={loading}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
            'bg-brand-600 hover:bg-brand-500 text-white',
            'disabled:opacity-50 disabled:cursor-not-allowed',
          )}
        >
          {loading
            ? <><Loader2 className="w-3 h-3 animate-spin" />Evaluating…</>
            : result
            ? <><RefreshCw className="w-3 h-3" />Re-evaluate</>
            : 'Evaluate plan'}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="text-xs text-red-500 dark:text-red-400 bg-red-50 dark:bg-red-400/10 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && !result && (
        <div className="space-y-2 animate-pulse">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-10 rounded-lg bg-slate-100 dark:bg-surface-700" />
          ))}
        </div>
      )}

      {/* Result */}
      {result && (
        <>
          {/* Global score gauge + metric bars */}
          <div className="flex flex-col sm:flex-row items-center gap-6">
            {/* Radial gauge */}
            <div className="relative w-28 h-28 shrink-0">
              <ResponsiveContainer width="100%" height="100%">
                <RadialBarChart
                  cx="50%" cy="50%"
                  innerRadius="68%" outerRadius="100%"
                  startAngle={90} endAngle={-270}
                  data={[
                    { value: 100, fill: trackColor },
                    { value: score, fill: color },
                  ]}
                >
                  <RadialBar dataKey="value" cornerRadius={6} />
                </RadialBarChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="text-2xl font-bold" style={{ color }}>{score}</span>
                <span className="text-[10px] text-slate-400">/ 100</span>
                <span className="text-xs font-semibold mt-0.5" style={{ color }}>{grade}</span>
              </div>
            </div>

            {/* Metric breakdown */}
            <div className="flex-1 w-full">
              <MetricBreakdown metrics={metrics} />
            </div>
          </div>

          {/* Detailed report */}
          {result.detailed_report && (
            <p className={cn(
              'text-xs leading-relaxed pt-3',
              'text-slate-500 dark:text-slate-400',
              'border-t border-slate-100 dark:border-white/[0.06]',
            )}>
              {result.detailed_report}
            </p>
          )}

          {/* Recommendations */}
          {result.recommendations.length > 0 && (
            <div className={cn(
              'space-y-1.5 pt-3',
              'border-t border-slate-100 dark:border-white/[0.06]',
            )}>
              <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
                Recommendations
              </p>
              {result.recommendations.map((r, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-400"
                >
                  <span className="text-brand-500 dark:text-brand-400 shrink-0 mt-0.5">›</span>
                  {r}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
