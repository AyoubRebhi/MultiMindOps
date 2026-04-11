import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Search, RefreshCw } from 'lucide-react'
import { useTaskList } from '@/hooks/useTasks'
import { StatusBadge } from '@/components/common/StatusBadge'
import { PageLoader } from '@/components/common/LoadingSpinner'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { timeAgo, formatDate, cn } from '@/lib/utils'
import type { TaskStatus } from '@/types'

const STATUS_FILTERS = [
  { key: 'all',                   label: 'All' },
  { key: 'in_progress',           label: 'Running' },
  { key: 'awaiting_human_review', label: 'Needs Review' },
  { key: 'completed',             label: 'Completed' },
  { key: 'failed',                label: 'Failed' },
]

export default function TaskList() {
  const { data: tasks, isLoading, error, refetch } = useTaskList()
  const [search, setSearch]       = useState('')
  const [statusFilter, setStatus] = useState('all')

  if (isLoading) return <PageLoader />
  if (error)     return <div className="p-6"><ErrorAlert message={error.message} /></div>

  const all = tasks ?? []
  const filtered = all
    .filter((t) => statusFilter === 'all' || t.status === statusFilter)
    .filter((t) =>
      !search ||
      t.prompt.toLowerCase().includes(search.toLowerCase()) ||
      t.id.includes(search)
    )
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())

  return (
    <div className="p-6 space-y-6 animate-slide-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">All Tasks</h1>
          <p className="text-sm text-slate-500 mt-1">{all.length} total tasks</p>
        </div>
        <button
          onClick={() => refetch()}
          className={cn(
            'p-2 rounded-lg transition-colors',
            'text-slate-400 dark:text-slate-500',
            'hover:text-slate-700 dark:hover:text-white',
            'hover:bg-slate-100 dark:hover:bg-white/[0.05]'
          )}
          title="Refresh"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 dark:text-slate-500 pointer-events-none" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search prompts…"
            className={cn(
              'w-full rounded-lg pl-9 pr-4 py-2 text-sm focus:outline-none transition-colors',
              'bg-white dark:bg-surface-800/50',
              'border border-slate-200 dark:border-white/[0.08]',
              'text-slate-800 dark:text-slate-200',
              'placeholder-slate-400 dark:placeholder-slate-600',
              'focus:border-brand-400 dark:focus:border-brand-500/40'
            )}
          />
        </div>

        {/* Status filter chips */}
        <div className="flex flex-wrap gap-1.5">
          {STATUS_FILTERS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setStatus(key)}
              className={cn(
                'px-3 py-1.5 rounded-full text-xs font-medium border transition-colors',
                statusFilter === key
                  ? 'bg-brand-50 dark:bg-brand-600/20 text-brand-700 dark:text-brand-300 border-brand-200 dark:border-brand-500/30'
                  : cn(
                      'text-slate-500 dark:text-slate-500',
                      'border-slate-200 dark:border-white/[0.06]',
                      'hover:text-slate-900 dark:hover:text-white',
                      'hover:border-slate-300 dark:hover:border-white/10'
                    )
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <div className={cn(
          'py-16 text-center text-sm rounded-xl border border-dashed',
          'text-slate-400 dark:text-slate-600',
          'border-slate-200 dark:border-white/[0.08]'
        )}>
          No tasks match your filters.
        </div>
      ) : (
        <div className={cn(
          'rounded-xl overflow-hidden',
          'bg-white dark:bg-surface-800/20',
          'border border-slate-200 dark:border-white/[0.06]'
        )}>
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-100 dark:border-white/[0.06]">
                {['Prompt', 'Status', 'Created', 'Updated', 'ID', ''].map((h) => (
                  <th
                    key={h}
                    className="py-3 px-4 text-left text-xs font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((task) => (
                <tr
                  key={task.id}
                  className={cn(
                    'border-b transition-colors group',
                    'border-slate-100 dark:border-white/[0.04]',
                    'hover:bg-slate-50 dark:hover:bg-white/[0.02]'
                  )}
                >
                  <td className="py-3 px-4 max-w-xs">
                    <Link
                      to={`/tasks/${task.id}`}
                      className="text-sm font-medium truncate block transition-colors text-slate-700 dark:text-slate-300 hover:text-brand-600 dark:hover:text-brand-300"
                    >
                      {task.prompt.length > 80
                        ? task.prompt.slice(0, 80) + '…'
                        : task.prompt}
                    </Link>
                  </td>
                  <td className="py-3 px-4 whitespace-nowrap">
                    <StatusBadge status={task.status as TaskStatus} size="sm" />
                  </td>
                  <td className="py-3 px-4 text-xs text-slate-400 dark:text-slate-500 whitespace-nowrap">
                    {timeAgo(task.created_at)}
                  </td>
                  <td className="py-3 px-4 text-xs text-slate-400 dark:text-slate-600 whitespace-nowrap">
                    {formatDate(task.updated_at)}
                  </td>
                  <td className="py-3 px-4">
                    <span className="text-xs text-slate-400 dark:text-slate-600 font-mono">
                      {task.id.slice(0, 8)}…
                    </span>
                  </td>
                  <td className="py-3 px-4 text-right">
                    <Link
                      to={`/tasks/${task.id}`}
                      className="text-slate-300 dark:text-slate-600 hover:text-brand-600 dark:hover:text-brand-400 transition-colors"
                    >
                      <ArrowRight className="w-4 h-4" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
