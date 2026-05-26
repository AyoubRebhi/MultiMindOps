import { Link } from 'react-router-dom'
import {
  Plus,
  Activity,
  AlertCircle,
  ArrowRight,
  Boxes,
  CheckCircle,
  ClipboardCheck,
  FolderGit2,
  Loader2,
  Sparkles,
  Workflow as WorkflowIcon,
} from 'lucide-react'
import { useTaskList } from '@/hooks/useTasks'
import { useProjectList } from '@/hooks/useProjects'
import { useAuth } from '@/context/AuthContext'
import { StatusBadge } from '@/components/common/StatusBadge'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { EmptyState } from '@/components/common/EmptyState'
import { SkeletonStatCard, Skeleton, SkeletonRow } from '@/components/common/Skeleton'
import { cn, timeAgo } from '@/lib/utils'
import type { TaskResponse } from '@/types'
import type { ProjectResponse } from '@/types/project'

// ─── Stat card ──────────────────────────────────────────────────────────────

interface StatCardProps {
  label: string
  value: number | string
  icon: React.ElementType
  iconClass: string
  hint?: string
  to?: string
}

function StatCard({ label, value, icon: Icon, iconClass, hint, to }: StatCardProps) {
  const body = (
    <div className={cn(
      'p-5 rounded-xl flex items-center gap-4 transition-colors',
      'bg-white dark:bg-surface-800/40',
      'border border-slate-200 dark:border-white/[0.06]',
      to && 'hover:border-brand-200 dark:hover:border-brand-500/30 hover:bg-brand-50/30 dark:hover:bg-brand-600/[0.04] cursor-pointer',
    )}>
      <div className={cn('p-3 rounded-lg', iconClass)}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="min-w-0">
        <div className="text-2xl font-bold text-slate-900 dark:text-white">{value}</div>
        <div className="text-xs text-slate-500 mt-0.5">{label}</div>
        {hint && <div className="text-[10px] text-slate-400 dark:text-slate-600 mt-0.5">{hint}</div>}
      </div>
    </div>
  )
  return to ? <Link to={to}>{body}</Link> : body
}

// ─── Recent task row ────────────────────────────────────────────────────────

function TaskRow({ task }: { task: TaskResponse }) {
  return (
    <tr className={cn(
      'border-b transition-colors group',
      'border-slate-100 dark:border-white/[0.04]',
      'hover:bg-slate-50 dark:hover:bg-white/[0.02]',
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

// ─── Activity feed row ──────────────────────────────────────────────────────

interface ActivityItem {
  kind: 'task' | 'project'
  id: string
  title: string
  status: string
  timestamp: string
  href: string
}

function buildActivity(tasks: TaskResponse[], projects: ProjectResponse[]): ActivityItem[] {
  const items: ActivityItem[] = []
  for (const t of tasks) {
    items.push({
      kind: 'task',
      id: t.id,
      title: t.prompt,
      status: t.status,
      timestamp: t.updated_at,
      href: `/tasks/${t.id}`,
    })
  }
  for (const p of projects) {
    items.push({
      kind: 'project',
      id: p.id,
      title: p.name,
      status: p.bootstrap_status,
      timestamp: p.updated_at,
      href: `/projects/${p.id}`,
    })
  }
  return items
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    .slice(0, 8)
}

function ActivityRow({ item }: { item: ActivityItem }) {
  const Icon = item.kind === 'task' ? Activity : FolderGit2
  return (
    <Link
      to={item.href}
      className={cn(
        'flex items-start gap-3 px-3 py-2.5 rounded-lg transition-colors',
        'hover:bg-slate-50 dark:hover:bg-white/[0.03]',
      )}
    >
      <div className={cn(
        'mt-0.5 p-1.5 rounded-md',
        item.kind === 'task'
          ? 'bg-brand-50 dark:bg-brand-600/15 text-brand-600 dark:text-brand-400'
          : 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
      )}>
        <Icon className="w-3.5 h-3.5" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-slate-700 dark:text-slate-300 truncate">
          {item.title}
        </p>
        <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
          {item.kind === 'task' ? 'Task' : 'Project'} · {item.status.replace(/_/g, ' ')} · {timeAgo(item.timestamp)}
        </p>
      </div>
    </Link>
  )
}

// ─── Infrastructure summary ─────────────────────────────────────────────────

interface InfraSummary {
  totalProjects: number
  ready: number
  bootstrapping: number
  failed: number
  archived: number
}

function summarizeProjects(projects: ProjectResponse[]): InfraSummary {
  let ready = 0, bootstrapping = 0, failed = 0, archived = 0
  for (const p of projects) {
    if (p.current_status === 'archived') archived++
    else if (p.bootstrap_status === 'ready') ready++
    else if (p.bootstrap_status === 'failed' || p.current_status === 'failed') failed++
    else bootstrapping++
  }
  return { totalProjects: projects.length, ready, bootstrapping, failed, archived }
}

function InfraSummaryPanel({ summary }: { summary: InfraSummary }) {
  const rows: { label: string; value: number; barClass: string; textClass: string }[] = [
    { label: 'Ready',         value: summary.ready,         barClass: 'bg-emerald-500',          textClass: 'text-emerald-600 dark:text-emerald-400' },
    { label: 'Bootstrapping', value: summary.bootstrapping, barClass: 'bg-blue-500 animate-pulse', textClass: 'text-blue-600 dark:text-blue-400' },
    { label: 'Failed',        value: summary.failed,        barClass: 'bg-red-500',              textClass: 'text-red-600 dark:text-red-400' },
    { label: 'Archived',      value: summary.archived,      barClass: 'bg-slate-400',            textClass: 'text-slate-500 dark:text-slate-400' },
  ]
  const denom = Math.max(summary.totalProjects, 1)

  return (
    <div className="space-y-3">
      {rows.map((r) => (
        <div key={r.label}>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className={cn('font-medium', r.textClass)}>{r.label}</span>
            <span className="text-slate-500 dark:text-slate-400">{r.value}</span>
          </div>
          <div className="h-1.5 rounded-full bg-slate-100 dark:bg-white/[0.05] overflow-hidden">
            <div
              className={cn('h-full rounded-full transition-all', r.barClass)}
              style={{ width: `${(r.value / denom) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const { user } = useAuth()
  const tasksQ = useTaskList()
  const projectsQ = useProjectList()

  const loading = tasksQ.isLoading || projectsQ.isLoading
  const fatalError = tasksQ.error ?? projectsQ.error

  const tasks = tasksQ.data ?? []
  const projects = projectsQ.data ?? []

  const activeWorkflows = tasks.filter((t) =>
    t.status === 'in_progress' || t.status === 'pending',
  ).length
  const pendingReviews = tasks.filter((t) => t.status === 'awaiting_human_review').length

  const recent = [...tasks]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 8)

  const activity = buildActivity(tasks, projects)
  const summary = summarizeProjects(projects)
  const greeting = user?.display_name ? `, ${user.display_name.split(' ')[0]}` : ''

  return (
    <div className="p-6 space-y-8 animate-slide-in">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            Welcome back{greeting}
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Here's the state of your DevSecOps automations.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/projects/new"
            className={cn(
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              'border border-slate-200 dark:border-white/[0.08]',
              'text-slate-700 dark:text-slate-300',
              'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
            )}
          >
            <FolderGit2 className="w-4 h-4" />
            New Project
          </Link>
          <Link
            to="/tasks/new"
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Task
          </Link>
        </div>
      </div>

      {fatalError && (
        <ErrorAlert
          title="Failed to load dashboard"
          message={fatalError.message}
        />
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {loading ? (
          <>
            <SkeletonStatCard />
            <SkeletonStatCard />
            <SkeletonStatCard />
            <SkeletonStatCard />
          </>
        ) : (
          <>
            <StatCard
              label="Projects"
              value={projects.length}
              icon={FolderGit2}
              iconClass="bg-brand-50 dark:bg-brand-600/20 text-brand-600 dark:text-brand-400"
              hint={summary.ready === projects.length && projects.length > 0 ? 'All ready' : `${summary.ready} ready`}
              to="/projects"
            />
            <StatCard
              label="Active workflows"
              value={activeWorkflows}
              icon={WorkflowIcon}
              iconClass="bg-blue-50 dark:bg-blue-500/15 text-blue-600 dark:text-blue-400"
              hint={activeWorkflows > 0 ? 'In progress' : 'Idle'}
              to="/tasks"
            />
            <StatCard
              label="Pending reviews"
              value={pendingReviews}
              icon={ClipboardCheck}
              iconClass="bg-amber-50 dark:bg-amber-500/15 text-amber-600 dark:text-amber-400"
              hint={pendingReviews > 0 ? 'Awaiting human' : 'All clear'}
              to="/tasks"
            />
            <StatCard
              label="Total tasks"
              value={tasks.length}
              icon={Activity}
              iconClass="bg-emerald-50 dark:bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
              to="/tasks"
            />
          </>
        )}
      </div>

      {/* Review alert */}
      {pendingReviews > 0 && (
        <div className={cn(
          'flex items-center gap-3 p-4 rounded-lg',
          'bg-amber-50 dark:bg-amber-500/10',
          'border border-amber-200 dark:border-amber-500/20',
        )}>
          <AlertCircle className="w-4 h-4 text-amber-500 dark:text-amber-400 shrink-0" />
          <p className="text-sm text-amber-700 dark:text-amber-300">
            {pendingReviews} task{pendingReviews > 1 ? 's' : ''} require{pendingReviews === 1 ? 's' : ''} human review.
          </p>
          <Link
            to="/tasks"
            className="ml-auto text-xs text-amber-600 dark:text-amber-400 hover:text-amber-800 dark:hover:text-amber-300 font-medium flex items-center gap-1"
          >
            View tasks <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      )}

      {/* Activity + Infra summary */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className={cn(
          'lg:col-span-2 p-5 rounded-xl',
          'bg-white dark:bg-surface-800/40',
          'border border-slate-200 dark:border-white/[0.06]',
        )}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-slate-900 dark:text-white">
              Recent activity
            </h2>
            {(tasksQ.isFetching || projectsQ.isFetching) && (
              <Loader2 className="w-3.5 h-3.5 text-slate-400 animate-spin" />
            )}
          </div>
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-3 py-2.5">
                  <Skeleton className="w-7 h-7 rounded-md" />
                  <div className="flex-1 space-y-1.5">
                    <Skeleton className="h-3.5 w-2/3" />
                    <Skeleton className="h-3 w-1/3" />
                  </div>
                </div>
              ))}
            </div>
          ) : activity.length === 0 ? (
            <EmptyState
              icon={Sparkles}
              title="Nothing happening yet"
              description="Create a project or kick off a task to see activity here."
              className="py-10"
            />
          ) : (
            <div className="-mx-2">
              {activity.map((item) => (
                <ActivityRow key={`${item.kind}:${item.id}`} item={item} />
              ))}
            </div>
          )}
        </div>

        <div className={cn(
          'p-5 rounded-xl',
          'bg-white dark:bg-surface-800/40',
          'border border-slate-200 dark:border-white/[0.06]',
        )}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-slate-900 dark:text-white">
              Infrastructure
            </h2>
            <Boxes className="w-4 h-4 text-slate-400" />
          </div>
          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i}>
                  <Skeleton className="h-3 w-1/3 mb-1.5" />
                  <Skeleton className="h-1.5 w-full" />
                </div>
              ))}
            </div>
          ) : projects.length === 0 ? (
            <EmptyState
              icon={FolderGit2}
              title="No projects yet"
              description="Projects appear here as you create them."
              className="py-8"
            />
          ) : (
            <InfraSummaryPanel summary={summary} />
          )}
        </div>
      </div>

      {/* Latest executions */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-slate-900 dark:text-white">
            Latest executions
          </h2>
          <Link
            to="/tasks"
            className="text-xs text-brand-600 dark:text-brand-400 hover:text-brand-500 dark:hover:text-brand-300 flex items-center gap-1"
          >
            View all <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        {loading ? (
          <div className={cn(
            'rounded-xl overflow-hidden',
            'bg-white dark:bg-surface-800/20',
            'border border-slate-200 dark:border-white/[0.06]',
          )}>
            <table className="w-full">
              <tbody>
                {Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} cols={4} />)}
              </tbody>
            </table>
          </div>
        ) : recent.length === 0 ? (
          <EmptyState
            icon={Activity}
            title="No tasks yet"
            description="Create a task and AI agents will generate, validate, and deploy infrastructure for you."
            action={
              <Link
                to="/tasks/new"
                className={cn(
                  'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                  'bg-brand-600 hover:bg-brand-500 text-white',
                )}
              >
                <Plus className="w-4 h-4" />
                Create your first task
              </Link>
            }
          />
        ) : (
          <div className={cn(
            'rounded-xl overflow-hidden',
            'bg-white dark:bg-surface-800/20',
            'border border-slate-200 dark:border-white/[0.06]',
          )}>
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-100 dark:border-white/[0.06]">
                  {['Prompt', 'Status', 'Created', ''].map((h) => (
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
                {recent.length > 0 && recent.length < 4 && (
                  <tr><td colSpan={4} className="py-2"><CheckCircle className="hidden" /></td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
