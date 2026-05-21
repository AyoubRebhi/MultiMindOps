import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  Boxes,
  Container,
  FileCode2,
  FolderGit2,
  GitBranch,
  Layers,
  ShieldCheck,
  Users,
  Workflow as WorkflowIcon,
} from 'lucide-react'
import {
  useProject,
  useProjectArtifacts,
  useProjectMembers,
  useProjectWorkflows,
} from '@/hooks/useProjects'
import { PageLoader } from '@/components/common/LoadingSpinner'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { cn, timeAgo } from '@/lib/utils'
import { ArtifactViewer } from '@/components/projects/ArtifactViewer'
import { WorkflowPanel } from '@/components/projects/WorkflowPanel'
import type { ArtifactResponse, WorkflowResponse } from '@/types/project'

const TABS = [
  { key: 'overview',     label: 'Overview',           icon: FolderGit2 },
  { key: 'analysis',     label: 'Code Analysis',      icon: FileCode2 },
  { key: 'architecture', label: 'Architecture Plans', icon: Layers },
  { key: 'docker',       label: 'Docker',             icon: Container },
  { key: 'terraform',    label: 'Terraform',          icon: Boxes },
  { key: 'kubernetes',   label: 'Kubernetes',         icon: Boxes },
  { key: 'validation',   label: 'Validation',         icon: ShieldCheck },
  { key: 'workflows',    label: 'Workflows',          icon: WorkflowIcon },
  { key: 'members',      label: 'Members',            icon: Users },
] as const

type TabKey = (typeof TABS)[number]['key']

// Maps an Artifact.artifact_type → tab. Tabs not in this map render nothing
// from the artifact list (handled by switch in the body).
const TYPE_BY_TAB: Partial<Record<TabKey, string[]>> = {
  analysis: ['analysis'],
  architecture: ['architecture_plan'],
  docker: ['docker'],
  terraform: ['terraform'],
  kubernetes: ['kubernetes'],
  validation: ['validation_report'],
}

export default function ProjectDetail() {
  const { id = '' } = useParams<{ id: string }>()
  const [tab, setTab] = useState<TabKey>('overview')

  const { data: project, isLoading, error } = useProject(id)
  const { data: artifacts } = useProjectArtifacts(id)
  const { data: workflows } = useProjectWorkflows(id)
  const { data: members } = useProjectMembers(id)

  if (isLoading) return <PageLoader />
  if (error)
    return (
      <div className="p-6">
        <ErrorAlert message={error.message} />
      </div>
    )
  if (!project) return null

  return (
    <div className="p-6 space-y-6 animate-slide-in">
      <Link
        to="/projects"
        className="flex items-center gap-2 text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> Projects
      </Link>

      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white truncate">
            {project.name}
          </h1>
          {project.description && (
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 max-w-2xl">
              {project.description}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2 mt-3 text-xs text-slate-500">
            <Chip>Status: {project.current_status}</Chip>
            {project.architecture_type && <Chip>{project.architecture_type}</Chip>}
            {project.default_strategy_tier && <Chip>Tier: {project.default_strategy_tier}</Chip>}
            {project.repository_url && (
              <span className="inline-flex items-center gap-1.5">
                <GitBranch className="w-3.5 h-3.5" />
                <span className="truncate max-w-[280px]">{project.repository_url}</span>
              </span>
            )}
          </div>
        </div>
      </header>

      <nav
        className={cn(
          'flex flex-wrap gap-1 p-1 rounded-xl',
          'bg-slate-50 dark:bg-surface-800/40',
          'border border-slate-200 dark:border-white/[0.06]',
        )}
      >
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              'inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
              tab === key
                ? 'bg-white dark:bg-surface-900 text-slate-900 dark:text-white border border-slate-200 dark:border-white/[0.08] shadow-sm'
                : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200',
            )}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </nav>

      <section>{renderTab(tab, id, project.id, artifacts ?? [], workflows ?? [], members ?? [])}</section>
    </div>
  )
}

function renderTab(
  tab: TabKey,
  routeProjectId: string,
  projectId: string,
  artifacts: ArtifactResponse[],
  workflows: WorkflowResponse[],
  members: { id: string; user_id: string; role: string; created_at: string }[],
) {
  if (tab === 'overview') {
    return (
      <OverviewTab
        projectId={routeProjectId}
        members={members.length}
        workflows={workflows}
        artifacts={artifacts}
      />
    )
  }
  if (tab === 'workflows') {
    return <WorkflowPanel projectId={routeProjectId} workflows={workflows} />
  }
  if (tab === 'members') {
    return <MembersTab members={members} />
  }
  const types = TYPE_BY_TAB[tab] ?? []
  const filtered = artifacts.filter((a) => types.includes(a.artifact_type))
  return (
    <ArtifactViewer
      projectId={projectId}
      artifacts={filtered}
      emptyMessage={`No ${tab} artifacts yet. Run the ${tab.toUpperCase()} phase from the Workflows tab.`}
    />
  )
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-100 dark:bg-white/[0.04] border border-slate-200 dark:border-white/[0.06]">
      {children}
    </span>
  )
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div
      className={cn(
        'p-4 rounded-xl',
        'bg-white dark:bg-surface-800/40',
        'border border-slate-200 dark:border-white/[0.06]',
      )}
    >
      <div className="text-2xl font-bold text-slate-900 dark:text-white">{value}</div>
      <div className="text-xs text-slate-500 mt-0.5">{label}</div>
    </div>
  )
}

function OverviewTab({
  projectId,
  members,
  workflows,
  artifacts,
}: {
  projectId: string
  members: number
  workflows: WorkflowResponse[]
  artifacts: ArtifactResponse[]
}) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Members" value={members} />
        <StatCard label="Workflows" value={workflows.length} />
        <StatCard label="Artifacts" value={artifacts.length} />
        <StatCard
          label="Last run"
          value={workflows[0] ? timeAgo(workflows[0].created_at) : '—'}
        />
      </div>
      <WorkflowPanel projectId={projectId} workflows={workflows} />
    </div>
  )
}

function MembersTab({
  members,
}: {
  members: { id: string; user_id: string; role: string; created_at: string }[]
}) {
  if (!members.length)
    return <Placeholder title="No members" body="Members will be invitable in a later phase." />
  return (
    <ul className="space-y-2">
      {members.map((m) => (
        <li
          key={m.id}
          className={cn(
            'flex items-center justify-between p-3 rounded-lg',
            'bg-white dark:bg-surface-800/40',
            'border border-slate-200 dark:border-white/[0.06]',
          )}
        >
          <div className="text-xs font-mono text-slate-500">{m.user_id}</div>
          <span className="text-xs px-2 py-0.5 rounded-full bg-brand-50 dark:bg-brand-600/20 text-brand-700 dark:text-brand-300">
            {m.role}
          </span>
        </li>
      ))}
    </ul>
  )
}

function Placeholder({ title, body }: { title: string; body: string }) {
  return (
    <div
      className={cn(
        'p-6 rounded-xl text-center',
        'border border-dashed border-slate-200 dark:border-white/[0.08]',
      )}
    >
      <div className="text-sm font-medium text-slate-700 dark:text-slate-300">{title}</div>
      <p className="text-xs text-slate-500 dark:text-slate-500 mt-1 max-w-md mx-auto">{body}</p>
    </div>
  )
}
