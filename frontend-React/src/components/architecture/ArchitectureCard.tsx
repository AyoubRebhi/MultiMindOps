import { Check, Star, DollarSign, Zap, Shield, Server, ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import type { ArchitecturePlan } from '@/types'

interface Props {
  plan: ArchitecturePlan
  isRecommended: boolean
  isSelected: boolean
  onSelect: () => void
  isLoading?: boolean
}

const PROFILE_COLOR: Record<string, string> = {
  startup:          'text-emerald-400',
  small_production: 'text-brand-400',
  medium_production:'text-amber-400',
  enterprise:       'text-rose-400',
}

const TIER_COLOR: Record<string, string> = {
  Low:  'bg-slate-700/60 text-slate-300',
  Medium: 'bg-brand-600/20 text-brand-300',
  High: 'bg-amber-500/15 text-amber-300',
}

export function ArchitectureCard({
  plan,
  isRecommended,
  isSelected,
  onSelect,
  isLoading,
}: Props) {
  const [showTips, setShowTips] = useState(false)

  const profileColor = PROFILE_COLOR[plan.cost_profile] ?? 'text-slate-400'
  const tierCls = TIER_COLOR[plan.scalability_tier] ?? 'bg-slate-700/60 text-slate-300'

  const borderCls = isSelected
    ? 'border-brand-500 shadow-[0_0_0_1px_rgba(99,102,241,0.4)]'
    : isRecommended
    ? 'border-brand-500/40'
    : 'border-slate-700/60'

  return (
    <div className={cn(
      'relative flex flex-col rounded-2xl border transition-all duration-200',
      'bg-slate-800/50',
      borderCls,
      isSelected && 'bg-brand-600/5',
    )}>

      {/* Recommended badge */}
      {isRecommended && (
        <div className={cn(
          'absolute -top-3 left-1/2 -translate-x-1/2',
          'flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold',
          'bg-brand-600 text-white shadow-md',
        )}>
          <Star className="w-3 h-3 fill-current" />
          Recommended
        </div>
      )}

      <div className="p-5 flex flex-col gap-4 flex-1">

        {/* Header */}
        <div className="flex items-start justify-between gap-2 pt-1">
          <div>
            <h3 className="text-base font-bold text-white">{plan.title}</h3>
            <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">{plan.description}</p>
          </div>
          <span className={cn('shrink-0 text-[10px] font-medium px-2 py-1 rounded-full', tierCls)}>
            {plan.scalability_tier}
          </span>
        </div>

        {/* Cost highlight */}
        <div className={cn(
          'rounded-xl px-4 py-3 border',
          isSelected
            ? 'bg-brand-600/10 border-brand-500/30'
            : 'bg-slate-900/40 border-slate-700/40',
        )}>
          <div className="flex items-baseline gap-1">
            <DollarSign className={cn('w-4 h-4 shrink-0', profileColor)} />
            <span className={cn('text-2xl font-bold tabular-nums', profileColor)}>
              {plan.monthly_cost.toFixed(2)}
            </span>
            <span className="text-xs text-slate-500">/month</span>
          </div>
          <p className="text-[11px] text-slate-500 mt-0.5">
            ≈ ${plan.yearly_cost.toFixed(0)}/year · {plan.cost_profile.replace(/_/g, ' ')}
          </p>
        </div>

        {/* Infrastructure badges */}
        <div className="flex flex-wrap gap-1.5">
          <InfoBadge icon={<Server className="w-3 h-3" />} label={plan.availability_level} />
          {(plan.aws_services ?? []).slice(0, 4).map((svc) => (
            <span
              key={svc}
              className="text-[10px] px-2 py-0.5 rounded-full bg-slate-700/50 text-slate-400 border border-slate-700/60"
            >
              {svc}
            </span>
          ))}
        </div>

        {/* Tradeoffs */}
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-2">
            Tradeoffs
          </p>
          <ul className="space-y-1.5">
            {plan.tradeoffs.slice(0, 4).map((t, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-slate-400">
                <div className="w-1.5 h-1.5 rounded-full bg-slate-600 shrink-0 mt-1.5" />
                {t}
              </li>
            ))}
          </ul>
        </div>

        {/* Optimization tips (collapsible) */}
        {plan.optimization_tips.length > 0 && (
          <div>
            <button
              onClick={() => setShowTips((v) => !v)}
              className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-brand-400 hover:text-brand-300 transition-colors"
            >
              <Zap className="w-3 h-3" />
              {showTips ? 'Hide' : 'Show'} optimization tips
              {showTips ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
            {showTips && (
              <ul className="mt-2 space-y-1.5">
                {plan.optimization_tips.slice(0, 3).map((tip, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-slate-400">
                    <Shield className="w-3 h-3 text-brand-400/60 shrink-0 mt-0.5" />
                    {tip}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* Select button */}
      <div className="px-5 pb-5">
        <button
          onClick={onSelect}
          disabled={isLoading}
          className={cn(
            'w-full flex items-center justify-center gap-2',
            'px-4 py-2.5 rounded-xl text-sm font-semibold transition-all',
            isSelected
              ? 'bg-brand-600 text-white shadow-md shadow-brand-600/20'
              : 'bg-slate-700/60 text-slate-300 border border-slate-600/60 hover:bg-slate-700 hover:text-white hover:border-slate-500',
            isLoading && 'opacity-50 cursor-not-allowed',
          )}
        >
          {isSelected ? (
            <>
              <Check className="w-4 h-4" />
              Selected
            </>
          ) : (
            'Select This Plan'
          )}
        </button>
      </div>
    </div>
  )
}

function InfoBadge({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-slate-700/50 text-slate-300 border border-slate-700/60">
      {icon}
      {label}
    </span>
  )
}
