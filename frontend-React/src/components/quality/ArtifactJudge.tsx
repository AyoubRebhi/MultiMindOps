import { useState } from 'react'
import { RadialBarChart, RadialBar, ResponsiveContainer } from 'recharts'
import { CheckCircle, Zap, Shield, Wrench, ChevronDown, ChevronUp, Loader2 } from 'lucide-react'
import { cn, scoreColor, scoreGrade } from '@/lib/utils'
import { useThemeStore } from '@/store/themeStore'
import { judgeArtifact } from '@/api/evaluation'
import type { JudgeResponse, ArtifactType } from '@/api/evaluation'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Props {
  artifactType: ArtifactType | string
  content: string
  context?: Record<string, string>
  /** If true the evaluation is triggered automatically on mount */
  autoRun?: boolean
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MetricBar({
  label,
  score,
  feedback,
  icon: Icon,
}: {
  label: string
  score: number
  feedback: string
  icon: React.ElementType
}) {
  const [open, setOpen] = useState(false)
  const color = scoreColor(score)

  return (
    <div className="space-y-1">
      <button
        className="w-full flex items-center gap-2 text-left group"
        onClick={() => setOpen((o) => !o)}
      >
        <Icon className="w-4 h-4 shrink-0 text-slate-400 dark:text-slate-500" />
        <span className="flex-1 text-xs font-medium text-slate-700 dark:text-slate-300">{label}</span>
        <span className="text-xs font-bold tabular-nums" style={{ color }}>{score}</span>
        {open
          ? <ChevronUp className="w-3 h-3 text-slate-400" />
          : <ChevronDown className="w-3 h-3 text-slate-400" />}
      </button>

      {/* Progress bar */}
      <div className="h-1.5 rounded-full bg-slate-200 dark:bg-surface-700">
        <div
          className="h-1.5 rounded-full transition-all duration-700"
          style={{ width: `${score}%`, backgroundColor: color }}
        />
      </div>

      {/* Feedback (collapsed by default) */}
      {open && (
        <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed pt-1 pl-6">
          {feedback}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ArtifactJudge({ artifactType, content, context, autoRun = false }: Props) {
  const isDark = useThemeStore((s) => s.theme === 'dark')
  const [result, setResult] = useState<JudgeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await judgeArtifact({ artifact_type: artifactType, artifact_content: content, context })
      setResult(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Evaluation failed')
    } finally {
      setLoading(false)
    }
  }

  // autoRun on first render
  useState(() => { if (autoRun) run() })

  const score = result?.global_score ?? 0
  const color = scoreColor(score)
  const grade = scoreGrade(score)
  const trackColor = isDark ? '#1e293b' : '#e2e8f0'

  const metrics = [
    { key: 'correction',      label: 'Correction',      icon: CheckCircle },
    { key: 'performance',     label: 'Performance',      icon: Zap         },
    { key: 'security',        label: 'Security',         icon: Shield      },
    { key: 'maintainability', label: 'Maintainability',  icon: Wrench      },
  ] as const

  return (
    <div className={cn(
      'rounded-xl p-5 space-y-5',
      'bg-white dark:bg-surface-800/40',
      'border border-slate-200 dark:border-white/[0.06]',
    )}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
          LLM Quality Evaluation
          <span className="ml-2 text-xs font-normal text-slate-400 dark:text-slate-500">
            ({artifactType})
          </span>
        </h3>
        <button
          onClick={run}
          disabled={loading}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
            'bg-brand-500 hover:bg-brand-600 text-white',
            'disabled:opacity-50 disabled:cursor-not-allowed',
          )}
        >
          {loading && <Loader2 className="w-3 h-3 animate-spin" />}
          {loading ? 'Evaluating…' : result ? 'Re-evaluate' : 'Evaluate'}
        </button>
      </div>

      {error && (
        <div className="text-xs text-red-500 dark:text-red-400 bg-red-50 dark:bg-red-400/10 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {result && (
        <>
          {/* Global score */}
          <div className="flex flex-col sm:flex-row items-center gap-6">
            <div className="relative w-28 h-28 shrink-0">
              <ResponsiveContainer width="100%" height="100%">
                <RadialBarChart
                  cx="50%" cy="50%"
                  innerRadius="68%" outerRadius="100%"
                  startAngle={90} endAngle={-270}
                  data={[{ value: 100, fill: trackColor }, { value: score, fill: color }]}
                >
                  <RadialBar dataKey="value" cornerRadius={6} />
                </RadialBarChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-2xl font-bold" style={{ color }}>{score}</span>
                <span className="text-[10px] text-slate-400">/ 100</span>
                <span className="text-xs font-semibold mt-0.5" style={{ color }}>{grade}</span>
              </div>
            </div>

            {/* Per-metric bars */}
            <div className="flex-1 w-full space-y-3">
              {metrics.map(({ key, label, icon }) => (
                <MetricBar
                  key={key}
                  label={label}
                  score={result.metrics[key].score}
                  feedback={result.metrics[key].feedback}
                  icon={icon}
                />
              ))}
            </div>
          </div>

          {/* Detailed report */}
          {result.detailed_report && (
            <p className={cn(
              'text-xs leading-relaxed pt-4',
              'text-slate-500 dark:text-slate-400',
              'border-t border-slate-100 dark:border-white/[0.06]',
            )}>
              {result.detailed_report}
            </p>
          )}

          {/* Recommendations */}
          {result.recommendations.length > 0 && (
            <div className={cn(
              'space-y-1.5 pt-4',
              'border-t border-slate-100 dark:border-white/[0.06]',
            )}>
              <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
                Top recommendations
              </p>
              {result.recommendations.map((r, i) => (
                <div key={i} className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-400">
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
