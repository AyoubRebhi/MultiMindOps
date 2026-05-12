import { Check, X, Minus } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ArchitecturePlan } from '@/types'

interface Props {
  plans: ArchitecturePlan[]
  selectedPlanId?: string
}

type CellValue = string | boolean | null

interface RowDef {
  label: string
  getValue: (p: ArchitecturePlan) => CellValue
}

const ROWS: RowDef[] = [
  {
    label: 'Monthly Cost',
    getValue: (p) => `$${p.monthly_cost.toFixed(2)}`,
  },
  {
    label: 'Yearly Estimate',
    getValue: (p) => `$${p.yearly_cost.toFixed(0)}`,
  },
  {
    label: 'Cost Profile',
    getValue: (p) => p.cost_profile.replace(/_/g, ' '),
  },
  {
    label: 'Scalability Tier',
    getValue: (p) => p.scalability_tier,
  },
  {
    label: 'Availability',
    getValue: (p) => p.availability_level,
  },
  {
    label: 'Multi-AZ',
    getValue: (p) => {
      const avail = p.availability_level.toLowerCase()
      return avail.includes('multi') || avail.includes('read')
    },
  },
  {
    label: 'HA Support',
    getValue: (p) => {
      const avail = p.availability_level.toLowerCase()
      return avail.includes('multi') || avail.includes('read')
    },
  },
  {
    label: 'Autoscaling',
    getValue: (p) => {
      const bp = p.infrastructure as Record<string, unknown>
      const scaling = (bp?.scaling as Record<string, unknown>) ?? {}
      return Boolean(scaling.auto_scaling)
    },
  },
  {
    label: 'Redis Cache',
    getValue: (p) => {
      const bp = p.infrastructure as Record<string, unknown>
      return Boolean(bp?.cache)
    },
  },
  {
    label: 'Compute',
    getValue: (p) => {
      const bp = p.infrastructure as Record<string, unknown>
      const compute = (bp?.compute as Record<string, unknown>) ?? {}
      return (compute.type as string) || 'EC2'
    },
  },
  {
    label: 'Read Replicas',
    getValue: (p) => {
      const bp = p.infrastructure as Record<string, unknown>
      const db = (bp?.database as Record<string, unknown>) ?? {}
      return Boolean(db.read_replicas)
    },
  },
  {
    label: 'AWS Services',
    getValue: (p) => `${(p.aws_services ?? []).length} services`,
  },
]

function Cell({ value, isSelected }: { value: CellValue; isSelected: boolean }) {
  const base = cn(
    'px-3 py-2.5 text-xs text-center',
    isSelected && 'bg-brand-600/5',
  )

  if (typeof value === 'boolean') {
    return (
      <td className={base}>
        {value ? (
          <Check className="w-3.5 h-3.5 text-emerald-400 mx-auto" />
        ) : (
          <X className="w-3.5 h-3.5 text-slate-600 mx-auto" />
        )}
      </td>
    )
  }
  if (value === null) {
    return (
      <td className={base}>
        <Minus className="w-3.5 h-3.5 text-slate-600 mx-auto" />
      </td>
    )
  }
  return (
    <td className={cn(base, 'text-slate-300 font-medium')}>
      {value}
    </td>
  )
}

export function ComparisonTable({ plans, selectedPlanId }: Props) {
  if (!plans.length) return null

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-700/50">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-slate-700/60">
            <th className="px-3 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-500 w-36 bg-slate-900/40">
              Feature
            </th>
            {plans.map((p) => (
              <th
                key={p.id}
                className={cn(
                  'px-3 py-3 text-center text-xs font-bold uppercase tracking-wider',
                  p.id === selectedPlanId
                    ? 'text-brand-300 bg-brand-600/10'
                    : 'text-slate-300 bg-slate-900/40',
                )}
              >
                {p.title}
                {p.id === selectedPlanId && (
                  <span className="ml-1.5 text-[9px] font-medium text-brand-400">(selected)</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row, ri) => (
            <tr
              key={row.label}
              className={cn(
                'border-b border-slate-800/60',
                ri % 2 === 0 ? 'bg-slate-900/20' : 'bg-transparent',
              )}
            >
              <td className="px-3 py-2.5 text-xs text-slate-500 font-medium whitespace-nowrap">
                {row.label}
              </td>
              {plans.map((p) => (
                <Cell
                  key={p.id}
                  value={row.getValue(p)}
                  isSelected={p.id === selectedPlanId}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
