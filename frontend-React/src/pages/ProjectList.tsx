import { Link } from 'react-router-dom'
import { FolderGit2, Plus, ArrowRight, GitBranch } from 'lucide-react'
import { useProjectList } from '@/hooks/useProjects'
import { PageLoader } from '@/components/common/LoadingSpinner'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { cn } from '@/lib/utils'
import { timeAgo } from '@/lib/utils'
import type { ProjectResponse } from '@/types/project'

export default function ProjectList() {
  const { data, isLoading, error } = useProjectList()

  if (isLoading) return <PageLoader />
  if (error)
    return (
      <div className="p-6">
        <ErrorAlert message={error.message} />
      </div>
    )

  const projects = data ?? []

  return (
    <div className="p-6 space-y-6 animate-slide-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Projects</h1>
          <p className="text-sm text-slate-500 mt-1">
            Persistent infrastructure targets. Each project owns workflows, artifacts, and validation history.
          </p>
        </div>
        <Link
          to="/projects/new"
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Project
        </Link>
      </div>

      {projects.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {projects.map((p) => (
            <ProjectCard key={p.id} project={p} />
          ))}
        </div>
      )}
    </div>
  )
}

function ProjectCard({ project }: { project: ProjectResponse }) {
  return (
    <Link
      to={`/projects/${project.id}`}
      className={cn(
        'group block p-5 rounded-xl transition-all',
        'bg-white dark:bg-surface-800/40',
        'border border-slate-200 dark:border-white/[0.06]',
        'hover:border-brand-300 dark:hover:border-brand-500/30',
        'hover:shadow-sm',
      )}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2 rounded-lg bg-brand-50 dark:bg-brand-600/20 text-brand-600 dark:text-brand-400">
            <FolderGit2 className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white truncate">
              {project.name}
            </h3>
            <p className="text-xs text-slate-500 mt-0.5 capitalize">
              {project.current_status}
            </p>
          </div>
        </div>
        <ArrowRight className="w-4 h-4 text-slate-300 dark:text-slate-700 group-hover:text-brand-600 dark:group-hover:text-brand-400 transition-colors" />
      </div>

      {project.description && (
        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
          {project.description}
        </p>
      )}

      {project.repository_url && (
        <div className="mt-3 flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500 truncate">
          <GitBranch className="w-3.5 h-3.5 shrink-0" />
          <span className="truncate">{project.repository_url}</span>
        </div>
      )}

      <div className="mt-4 flex items-center justify-between text-xs text-slate-400 dark:text-slate-600">
        <span>{project.architecture_type ?? '—'}</span>
        <span>{timeAgo(project.updated_at)}</span>
      </div>
    </Link>
  )
}

function EmptyState() {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center py-20 text-center rounded-xl',
        'border border-dashed border-slate-200 dark:border-white/[0.08]',
      )}
    >
      <FolderGit2 className="w-10 h-10 text-slate-300 dark:text-slate-700 mb-4" />
      <p className="text-sm text-slate-500 dark:text-slate-400 max-w-md">
        No projects yet. Create one to start collecting persistent artifacts, validation history, and
        re-runnable workflows.
      </p>
      <Link
        to="/projects/new"
        className={cn(
          'mt-5 flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
          'bg-brand-50 dark:bg-brand-600/20',
          'hover:bg-brand-100 dark:hover:bg-brand-600/30',
          'text-brand-700 dark:text-brand-300',
          'border border-brand-200 dark:border-brand-500/20',
        )}
      >
        <Plus className="w-4 h-4" />
        Create your first project
      </Link>
    </div>
  )
}
