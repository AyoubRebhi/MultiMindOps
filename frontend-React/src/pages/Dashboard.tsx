import { Link } from 'react-router-dom'
import {
  Plus,
  CheckCircle,
  XCircle,
  Clock,
  Activity,
  ArrowRight,
  AlertCircle,
} from 'lucide-react'
import { useTaskList } from '@/hooks/useTasks'
import { StatusBadge } from '@/components/common/StatusBadge'
import { PageLoader } from '@/components/common/LoadingSpinner'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { timeAgo } from '@/lib/utils'
import { cn } from '@/lib/utils'
import type { TaskResponse } from '@/types'

function StatCard({
  label,
  value,
  icon: Icon,
  iconClass,
}: {
  label: string
  value: number
  icon: React.ElementType
  iconClass: string
}) {
  return (
    <div className={cn(
      'p-5 rounded-xl flex items-center gap-4 transition-colors',
      'bg-white dark:bg-surface-800/40',
      'border border-slate-200 dark:border-white/[0.06]'
    )}>
      <div className={cn('p-3 rounded-lg', iconClass)}>
        <Icon className="w-5 h-5" />
      </div>
      <div>
        <div className="text-2xl font-bold text-slate-900 dark:text-white">{value}</div>
        <div className="text-xs text-slate-500 mt-0.5">{label}</div>
      </div>
    </div>
  )
}

function TaskRow({ task }: { task: TaskResponse }) {
  return (
    <tr className={cn(
      'border-b transition-colors group',
      'border-slate-100 dark:border-white/[0.04]',
      'hover:bg-slate-50 dark:hover:bg-white/[0.02]'
    )}>
      <td className="py-3 px-4">
        <Link
          to={`/tasks/${task.id}`}
          className="text-sm text-slate-700 dark:text-slate-300 hover:text-brand-600 dark:hover:text-brand-300 font-medium truncate block max-w-xs transition-colors"
        >
          {task.prompt.length > 80 ? task.prompt.slice(0, 80) + '…' : task.prompt}
        </Link>
      </td>
      <td className="py-3 px-4">
        <StatusBadge status={task.status} size="sm" />
      </td>
      <td className="py-3 px-4 text-xs text-slate-400 dark:text-slate-500 whitespace-nowrap">
        {timeAgo(task.created_at)}
      </td>
      <td className="py-3 px-4">
        <div className="text-xs text-slate-400 dark:text-slate-600 font-mono truncate max-w-[120px]">
          {task.id.slice(0, 8)}…
        </div>
      </td>
      <td className="py-3 px-4 text-right">
        <Link
          to={`/tasks/${task.id}`}
          className="text-slate-400 dark:text-slate-600 hover:text-brand-600 dark:hover:text-brand-400 transition-colors"
        >
          <ArrowRight className="w-4 h-4" />
        </Link>
      </td>
    </tr>
  )
}

export default function Dashboard() {
  const { data: tasks, isLoading, error } = useTaskList()

  if (isLoading) return <PageLoader />
  if (error) return (
    <div className="p-6">
      <ErrorAlert message={error.message} />
    </div>
  )

  const all        = tasks ?? []
  const completed  = all.filter((t) =>
    t.status === 'completed' || t.status === 'human_approved' || t.status === 'human_approved_with_changes'
  ).length
  const failed     = all.filter((t) => t.status === 'failed').length
  const running    = all.filter((t) => t.status === 'in_progress' || t.status === 'pending').length
  const needReview = all.filter((t) => t.status === 'awaiting_human_review').length

  const recent = [...all]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 10)

  return (
    <div className="p-6 space-y-8 animate-slide-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Dashboard</h1>
          <p className="text-sm text-slate-500 mt-1">AI-powered DevSecOps automation overview</p>
        </div>
        <Link
          to="/tasks/new"
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Task
        </Link>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total tasks"
          value={all.length}
          icon={Activity}
          iconClass="bg-brand-50 dark:bg-brand-600/20 text-brand-600 dark:text-brand-400"
        />
        <StatCard
          label="Completed"
          value={completed}
          icon={CheckCircle}
          iconClass="bg-emerald-50 dark:bg-emerald-500/20 text-emerald-600 dark:text-emerald-400"
        />
        <StatCard
          label="Failed"
          value={failed}
          icon={XCircle}
          iconClass="bg-red-50 dark:bg-red-500/20 text-red-600 dark:text-red-400"
        />
        <StatCard
          label="Running / Queue"
          value={running}
          icon={Clock}
          iconClass="bg-blue-50 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400"
        />
      </div>

      {/* Review alert */}
      {needReview > 0 && (
        <div className={cn(
          'flex items-center gap-3 p-4 rounded-lg',
          'bg-amber-50 dark:bg-amber-500/10',
          'border border-amber-200 dark:border-amber-500/20'
        )}>
          <AlertCircle className="w-4 h-4 text-amber-500 dark:text-amber-400 shrink-0" />
          <p className="text-sm text-amber-700 dark:text-amber-300">
            {needReview} task{needReview > 1 ? 's' : ''} require{needReview === 1 ? 's' : ''} human review.
          </p>
          <Link
            to="/tasks"
            className="ml-auto text-xs text-amber-600 dark:text-amber-400 hover:text-amber-800 dark:hover:text-amber-300 font-medium flex items-center gap-1"
          >
            View tasks <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      )}

      {/* Recent tasks table */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-slate-900 dark:text-white">Recent tasks</h2>
          <Link
            to="/tasks"
            className="text-xs text-brand-600 dark:text-brand-400 hover:text-brand-500 dark:hover:text-brand-300 flex items-center gap-1"
          >
            View all <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        {recent.length === 0 ? (
          <div className={cn(
            'flex flex-col items-center justify-center py-16 text-center rounded-xl',
            'border border-dashed border-slate-200 dark:border-white/[0.08]'
          )}>
            <Activity className="w-8 h-8 text-slate-300 dark:text-slate-700 mb-3" />
            <p className="text-sm text-slate-400 dark:text-slate-500">No tasks yet</p>
            <Link
              to="/tasks/new"
              className={cn(
                'mt-4 flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                'bg-brand-50 dark:bg-brand-600/20',
                'hover:bg-brand-100 dark:hover:bg-brand-600/30',
                'text-brand-700 dark:text-brand-300',
                'border border-brand-200 dark:border-brand-500/20'
              )}
            >
              <Plus className="w-4 h-4" />
              Create your first task
            </Link>
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
                  {['Prompt', 'Status', 'Created', 'ID', ''].map((h) => (
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
                {recent.map((task) => <TaskRow key={task.id} task={task} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
