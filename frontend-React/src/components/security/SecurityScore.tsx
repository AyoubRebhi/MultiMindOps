import { RadialBarChart, RadialBar, ResponsiveContainer } from 'recharts'
import { Shield, ShieldAlert, ShieldCheck } from 'lucide-react'
import { cn, scoreColor, scoreGrade } from '@/lib/utils'
import { useThemeStore } from '@/store/themeStore'
import type { SecurityAnalysis } from '@/types'

interface Props {
  security: SecurityAnalysis
  compact?: boolean
}

function SevCount({ label, count, color }: { label: string; count?: number; color: string }) {
  return (
    <div className="text-center">
      <div className={cn('text-xl font-bold', color)}>{count ?? 0}</div>
      <div className="text-xs text-slate-500 dark:text-slate-500">{label}</div>
    </div>
  )
}

export function SecurityScore({ security, compact }: Props) {
  const isDark = useThemeStore((s) => s.theme === 'dark')

  const score = security.score ?? 0
  const color = scoreColor(score)
  const grade = scoreGrade(score)

  const vulns  = security.vulnerabilities ?? []
  const crit   = security.critical  ?? vulns.filter((v) => v.severity === 'critical').length
  const high   = security.high      ?? vulns.filter((v) => v.severity === 'high').length
  const medium = security.medium    ?? vulns.filter((v) => v.severity === 'medium').length
  const low    = security.low       ?? vulns.filter((v) => v.severity === 'low').length

  const ShieldIcon = score >= 70 ? ShieldCheck : score >= 40 ? Shield : ShieldAlert

  // Chart track color — adapts to theme
  const trackColor = isDark ? '#1e293b' : '#e2e8f0'
  // Progress bar track
  const barTrack = isDark ? 'bg-surface-700' : 'bg-slate-200'

  if (compact) {
    return (
      <div className={cn(
        'flex items-center gap-4 p-3 rounded-lg',
        'bg-slate-50 dark:bg-surface-800/40',
        'border border-slate-200 dark:border-white/[0.06]'
      )}>
        <ShieldIcon className="w-5 h-5 shrink-0" style={{ color }} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-slate-500 dark:text-slate-400">Security score</span>
            <span className="font-bold" style={{ color }}>
              {score}/100 · {grade}
            </span>
          </div>
          <div className={cn('h-1.5 rounded-full', barTrack)}>
            <div
              className="h-1.5 rounded-full transition-all duration-700"
              style={{ width: `${score}%`, backgroundColor: color }}
            />
          </div>
        </div>
        <div className="flex gap-3 text-xs shrink-0">
          {crit   > 0 && <span className="text-red-500 dark:text-red-400">{crit}C</span>}
          {high   > 0 && <span className="text-orange-500 dark:text-orange-400">{high}H</span>}
          {medium > 0 && <span className="text-amber-500 dark:text-amber-400">{medium}M</span>}
          {low    > 0 && <span className="text-blue-500 dark:text-blue-400">{low}L</span>}
        </div>
      </div>
    )
  }

  const chartData = [{ value: score, fill: color }]

  return (
    <div className={cn(
      'p-6 rounded-xl',
      'bg-white dark:bg-surface-800/40',
      'border border-slate-200 dark:border-white/[0.06]'
    )}>
      <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-6">
        Security Analysis
      </h3>

      <div className="flex flex-col sm:flex-row items-center gap-8">
        {/* Radial chart */}
        <div className="relative w-40 h-40 shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <RadialBarChart
              cx="50%"
              cy="50%"
              innerRadius="70%"
              outerRadius="100%"
              startAngle={90}
              endAngle={-270}
              data={[{ value: 100, fill: trackColor }, ...chartData]}
            >
              <RadialBar dataKey="value" cornerRadius={8} />
            </RadialBarChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-3xl font-bold" style={{ color }}>{score}</span>
            <span className="text-xs text-slate-400 dark:text-slate-500">/ 100</span>
            <span className="text-sm font-semibold mt-1" style={{ color }}>{grade}</span>
          </div>
        </div>

        {/* Stats */}
        <div className="flex-1 space-y-4 w-full">
          <div className="grid grid-cols-4 gap-4">
            <SevCount label="Critical" count={crit}   color="text-red-500 dark:text-red-400" />
            <SevCount label="High"     count={high}   color="text-orange-500 dark:text-orange-400" />
            <SevCount label="Medium"   count={medium} color="text-amber-500 dark:text-amber-400" />
            <SevCount label="Low"      count={low}    color="text-blue-500 dark:text-blue-400" />
          </div>

          {security.summary && (
            <p className={cn(
              'text-xs leading-relaxed pt-4',
              'text-slate-500 dark:text-slate-400',
              'border-t border-slate-100 dark:border-white/[0.06]'
            )}>
              {security.summary}
            </p>
          )}

          {security.recommendations && security.recommendations.length > 0 && (
            <div className={cn(
              'space-y-1.5 pt-4',
              'border-t border-slate-100 dark:border-white/[0.06]'
            )}>
              {security.recommendations.slice(0, 3).map((r, i) => (
                <div key={i} className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-400">
                  <span className="text-brand-500 dark:text-brand-400 shrink-0 mt-0.5">›</span>
                  {r}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
