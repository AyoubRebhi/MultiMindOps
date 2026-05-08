import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend,
} from 'recharts'
import { useState } from 'react'
import { BarChart2, PieChart as PieIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  breakdown: Record<string, number>
  currency?: string
}

const COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#06b6d4',
  '#f97316', '#84cc16', '#ec4899', '#6366f1',
]

const SERVICE_LABELS: Record<string, string> = {
  compute:       'Compute (EC2/ECS)',
  database:      'Database (RDS)',
  s3:            'Storage (S3)',
  cloudwatch:    'Monitoring',
  data_transfer: 'Data Transfer',
  load_balancer: 'Load Balancer',
  lambda:        'Lambda',
  elasticache:   'ElastiCache',
  eks:           'EKS',
  ecr:           'ECR',
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function CustomTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const { name, value } = payload[0]
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 shadow-xl">
      <p className="text-xs text-slate-400">{name}</p>
      <p className="text-sm font-bold text-white">${Number(value).toFixed(2)}/mo</p>
    </div>
  )
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function CustomPieLabel({ cx, cy, midAngle, innerRadius, outerRadius, percent }: any) {
  if (percent < 0.05) return null
  const RADIAN = Math.PI / 180
  const radius = innerRadius + (outerRadius - innerRadius) * 0.55
  const x = cx + radius * Math.cos(-midAngle * RADIAN)
  const y = cy + radius * Math.sin(-midAngle * RADIAN)
  return (
    <text x={x} y={y} fill="white" textAnchor="middle" dominantBaseline="central" fontSize={10} fontWeight={600}>
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  )
}

export function CostBreakdownChart({ breakdown, currency = 'USD' }: Props) {
  const [view, setView] = useState<'pie' | 'bar'>('pie')

  const data = Object.entries(breakdown)
    .filter(([, v]) => v > 0)
    .sort(([, a], [, b]) => b - a)
    .map(([key, value], i) => ({
      name: SERVICE_LABELS[key] ?? key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
      value: Number(value.toFixed(2)),
      color: COLORS[i % COLORS.length],
    }))

  return (
    <div className="space-y-4">
      {/* View toggle */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">Cost by Service</p>
        <div className="flex items-center gap-1 bg-slate-800/80 rounded-lg p-0.5 border border-slate-700/50">
          <button
            onClick={() => setView('pie')}
            className={cn(
              'flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-colors',
              view === 'pie' ? 'bg-slate-700 text-white' : 'text-slate-500 hover:text-slate-300',
            )}
          >
            <PieIcon className="w-3 h-3" /> Pie
          </button>
          <button
            onClick={() => setView('bar')}
            className={cn(
              'flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-colors',
              view === 'bar' ? 'bg-slate-700 text-white' : 'text-slate-500 hover:text-slate-300',
            )}
          >
            <BarChart2 className="w-3 h-3" /> Bar
          </button>
        </div>
      </div>

      {/* Chart */}
      <div className="h-[260px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          {view === 'pie' ? (
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={55}
                outerRadius={100}
                paddingAngle={2}
                dataKey="value"
                labelLine={false}
                label={CustomPieLabel}
                animationBegin={0}
                animationDuration={600}
              >
                {data.map((entry, i) => (
                  <Cell key={`cell-${i}`} fill={entry.color} stroke="transparent" />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
              <Legend
                iconType="circle"
                iconSize={8}
                formatter={(value) => (
                  <span className="text-[11px] text-slate-400">{value}</span>
                )}
              />
            </PieChart>
          ) : (
            <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
              <XAxis
                dataKey="name"
                tick={{ fontSize: 10, fill: '#64748b' }}
                axisLine={false}
                tickLine={false}
                interval={0}
                angle={-20}
                textAnchor="end"
                height={50}
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#64748b' }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => `$${v}`}
              />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="value" name={`Cost (${currency})`} radius={[4, 4, 0, 0]} animationDuration={600}>
                {data.map((entry, i) => (
                  <Cell key={`bar-${i}`} fill={entry.color} />
                ))}
              </Bar>
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>

      {/* Breakdown table */}
      <div className="rounded-xl overflow-hidden border border-slate-700/50">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-800/80 border-b border-slate-700/50">
              <th className="px-3 py-2 text-left text-slate-400 font-medium">Service</th>
              <th className="px-3 py-2 text-right text-slate-400 font-medium">Monthly</th>
              <th className="px-3 py-2 text-right text-slate-400 font-medium">Annual</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row, i) => (
              <tr key={i} className="border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors">
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ background: row.color }} />
                    <span className="text-slate-300">{row.name}</span>
                  </div>
                </td>
                <td className="px-3 py-2 text-right text-slate-300 font-mono">${row.value.toFixed(2)}</td>
                <td className="px-3 py-2 text-right text-slate-500 font-mono">${(row.value * 12).toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
