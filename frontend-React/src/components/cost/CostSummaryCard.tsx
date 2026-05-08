import { DollarSign, Server, Tag, BarChart2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  monthlyCost: number
  costProfile: string
  currency?: string
}

const PROFILE_LABELS: Record<string, { label: string; color: string }> = {
  small_production:  { label: 'Small Production',  color: 'text-green-400  bg-green-900/30  border-green-700/40'  },
  medium_production: { label: 'Medium Production', color: 'text-yellow-400 bg-yellow-900/30 border-yellow-700/40' },
  large_production:  { label: 'Large Production',  color: 'text-orange-400 bg-orange-900/30 border-orange-700/40' },
  development:       { label: 'Development',       color: 'text-sky-400    bg-sky-900/30    border-sky-700/40'    },
  enterprise:        { label: 'Enterprise',         color: 'text-purple-400 bg-purple-900/30 border-purple-700/40' },
}

export function CostSummaryCard({ monthlyCost, costProfile, currency = 'USD' }: Props) {
  const profile = PROFILE_LABELS[costProfile] ?? { label: costProfile, color: 'text-slate-400 bg-slate-800/60 border-slate-700/40' }
  const annual = (monthlyCost * 12).toFixed(0)

  return (
    <div className="grid grid-cols-2 gap-4">
      {/* Monthly total */}
      <div className={cn(
        'col-span-2 flex items-center justify-between p-5 rounded-xl',
        'bg-gradient-to-br from-slate-800/80 to-slate-900/80',
        'border border-slate-700/60',
      )}>
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
            <DollarSign className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <p className="text-xs text-slate-500 font-medium uppercase tracking-wide">Estimated Monthly</p>
            <p className="text-3xl font-bold text-white mt-0.5">
              ${monthlyCost.toFixed(2)}
              <span className="text-sm font-normal text-slate-500 ml-1">{currency}</span>
            </p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-xs text-slate-500">Annual estimate</p>
          <p className="text-xl font-semibold text-slate-300">${annual}</p>
        </div>
      </div>

      {/* Cost profile */}
      <div className={cn(
        'flex items-center gap-3 p-4 rounded-xl',
        'bg-slate-800/60 border border-slate-700/50',
      )}>
        <div className="p-2 rounded-lg bg-slate-700/60">
          <Tag className="w-4 h-4 text-slate-400" />
        </div>
        <div>
          <p className="text-xs text-slate-500 font-medium">Cost Profile</p>
          <span className={cn('text-xs font-semibold px-2 py-0.5 rounded border mt-1 inline-block', profile.color)}>
            {profile.label}
          </span>
        </div>
      </div>

      {/* Architecture scale */}
      <div className={cn(
        'flex items-center gap-3 p-4 rounded-xl',
        'bg-slate-800/60 border border-slate-700/50',
      )}>
        <div className="p-2 rounded-lg bg-slate-700/60">
          <Server className="w-4 h-4 text-slate-400" />
        </div>
        <div>
          <p className="text-xs text-slate-500 font-medium">Cloud Provider</p>
          <p className="text-sm font-semibold text-slate-200 mt-0.5">AWS</p>
        </div>
      </div>

      {/* Pricing model note */}
      <div className={cn(
        'col-span-2 flex items-center gap-2.5 px-4 py-2.5 rounded-lg',
        'bg-blue-500/5 border border-blue-500/15',
      )}>
        <BarChart2 className="w-3.5 h-3.5 text-blue-400 shrink-0" />
        <p className="text-xs text-blue-300/80">
          Estimates based on on-demand pricing. Reserved instances can reduce costs by 30–60%.
        </p>
      </div>
    </div>
  )
}
