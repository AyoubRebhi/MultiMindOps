import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowLeft,
  Boxes,
  Brain,
  Container,
  FileCode2,
  FolderGit2,
  GitBranch,
  Layers,
  RefreshCcw,
  ShieldCheck,
  Sparkles,
  Users,
  Workflow as WorkflowIcon,
} from 'lucide-react'
import {
  useProject,
  useProjectArtifacts,
  useProjectContext,
  useProjectMembers,
  useProjectRole,
  useProjectWorkflows,
  useRetryBootstrap,
} from '@/hooks/useProjects'
import { PageLoader } from '@/components/common/LoadingSpinner'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { cn, timeAgo } from '@/lib/utils'
import { ArtifactViewer } from '@/components/projects/ArtifactViewer'
import { WorkflowPanel } from '@/components/projects/WorkflowPanel'
import { ProjectContextPanel } from '@/components/projects/ProjectContextPanel'
import { MembersTab } from '@/components/projects/MembersTab'
import { RoleBadge } from '@/components/projects/RoleBadge'
import { CodeAnalysisPanel } from '@/components/projects/CodeAnalysisPanel'
import { useAuth } from '@/context/AuthContext'
import { ArchitectureDecisionPanel } from '@/components/architecture/ArchitectureDecisionPanel'
import { WorkflowTimeline } from '@/components/workflow/WorkflowTimeline'
import type {
  ArtifactResponse,
  ProjectBootstrapStatus,
  ProjectContextResponse,
  ProjectMemberResponse,
  ProjectResponse,
  ProjectRole,
  WorkflowResponse,
} from '@/types/project'

const TABS = [
  { key: 'overview',     label: 'Overview',           icon: FolderGit2 },
  { key: 'analysis',     label: 'Code Analysis',      icon: FileCode2 },
  { key: 'architecture', label: 'Architecture Plans', icon: Layers },
  { key: 'docker',       label: 'Docker',             icon: Container },
  { key: 'terraform',    label: 'Terraform',          icon: Boxes },
  { key: 'kubernetes',   label: 'Kubernetes',         icon: Boxes },
  { key: 'validation',   label: 'Validation',         icon: ShieldCheck },
  { key: 'workflows',    label: 'Workflows',          icon: WorkflowIcon },
  { key: 'context',      label: 'Project Memory',     icon: Brain },
  { key: 'members',      label: 'Members',            icon: Users },
] as const

type TabKey = (typeof TABS)[number]['key']

// Maps an Artifact.artifact_type → tab. Tabs not in this map render nothing
// from the artifact list (handled by switch in the body).
// NOTE: 'analysis' is handled by CodeAnalysisPanel (ProjectContext, not Artifact),
// so it is intentionally absent here.
const TYPE_BY_TAB: Partial<Record<TabKey, string[]>> = {
  docker: ['docker'],
  terraform: ['terraform'],
  kubernetes: ['kubernetes'],
  validation: ['validation_report'],
}

const APPROVER_ROLES = new Set<ProjectRole>(['CLOUD_ARCHITECT', 'OWNER', 'ADMIN'])
const CONTRIBUTOR_ROLES = new Set<ProjectRole>(['DEVELOPER', 'CLOUD_ARCHITECT', 'OWNER', 'ADMIN'])

export default function ProjectDetail() {
  const { id = '' } = useParams<{ id: string }>()
  const [tab, setTab] = useState<TabKey>('overview')

  const { data: project, isLoading, error } = useProject(id)
  const { data: artifacts } = useProjectArtifacts(id)
  const { data: workflows } = useProjectWorkflows(id)
  const { data: members } = useProjectMembers(id)
  const role = useProjectRole(id)
  const { user } = useAuth()

  const latestWorkflow = workflows?.[0]
  const canSelectPlan   = !!role && CONTRIBUTOR_ROLES.has(role)
  const canRegenerate   = !!role && CONTRIBUTOR_ROLES.has(role)
  const canApprove      = !!role && APPROVER_ROLES.has(role)

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
            <BootstrapChip status={project.bootstrap_status} />
            {project.architecture_type && <Chip>{project.architecture_type}</Chip>}
            {project.default_strategy_tier && <Chip>Tier: {project.default_strategy_tier}</Chip>}
            {role && (
              <span className="inline-flex items-center gap-1.5">
                <span className="text-slate-400 dark:text-slate-500">Your role:</span>
                <RoleBadge role={role} />
              </span>
            )}
            {project.repository_url && (
              <span className="inline-flex items-center gap-1.5">
                <GitBranch className="w-3.5 h-3.5" />
                <span className="truncate max-w-[280px]">{project.repository_url}</span>
              </span>
            )}
          </div>
        </div>
      </header>

      <BootstrapBanner project={project} />

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

      <section>
        {renderTab({
          tab,
          projectId: id,
          artifacts: artifacts ?? [],
          workflows: workflows ?? [],
          members: members ?? [],
          latestWorkflow,
          canSelectPlan,
          canRegenerate,
          canApprove,
          currentUserRole: role,
          currentUserId: user?.id ?? null,
        })}
      </section>
    </div>
  )
}

interface RenderTabArgs {
  tab: TabKey
  projectId: string
  artifacts: ArtifactResponse[]
  workflows: WorkflowResponse[]
  members: ProjectMemberResponse[]
  latestWorkflow?: WorkflowResponse
  canSelectPlan: boolean
  canRegenerate: boolean
  canApprove: boolean
  currentUserRole: ProjectRole | null
  currentUserId: string | null
}

function renderTab({
  tab,
  projectId,
  artifacts,
  workflows,
  members,
  latestWorkflow,
  canSelectPlan,
  canRegenerate,
  currentUserRole,
  currentUserId,
}: RenderTabArgs) {
  if (tab === 'overview') {
    return (
      <OverviewTab
        projectId={projectId}
        membersCount={members.length}
        workflows={workflows}
        artifacts={artifacts}
        latestWorkflow={latestWorkflow}
      />
    )
  }
  if (tab === 'workflows') {
    return (
      <div className="space-y-5">
        {latestWorkflow && (
          <WorkflowTimeline workflow={latestWorkflow} artifacts={artifacts} />
        )}
        <WorkflowPanel projectId={projectId} workflows={workflows} />
      </div>
    )
  }
  if (tab === 'architecture') {
    return (
      <ArchitectureDecisionPanel
        projectId={projectId}
        workflow={latestWorkflow}
        canSelect={canSelectPlan}
        canRegenerate={canRegenerate}
      />
    )
  }
  if (tab === 'analysis') {
    return <CodeAnalysisPanel projectId={projectId} />
  }
  if (tab === 'context') {
    return <ProjectContextPanel projectId={projectId} />
  }
  if (tab === 'members') {
    return (
      <MembersTab
        projectId={projectId}
        members={members}
        currentUserRole={currentUserRole}
        currentUserId={currentUserId}
      />
    )
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
  membersCount,
  workflows,
  artifacts,
  latestWorkflow,
}: {
  projectId: string
  membersCount: number
  workflows: WorkflowResponse[]
  artifacts: ArtifactResponse[]
  latestWorkflow?: WorkflowResponse
}) {
  const { data: context, isLoading: ctxLoading } = useProjectContext(projectId)

  const approvedCount = useMemo(
    () => artifacts.filter((a) => a.approval_state === 'approved').length,
    [artifacts],
  )
  const pendingReviewCount = useMemo(
    () => artifacts.filter((a) => a.approval_state === 'pending_review').length,
    [artifacts],
  )

  // Pluck digests off the ProjectContext list. Each context_type appears
  // at most once per project, so a Map keyed by type is cheap to build.
  const ctxByType = useMemo(() => {
    const map = new Map<string, ProjectContextResponse>()
    for (const row of context ?? []) map.set(row.context_type, row)
    return map
  }, [context])

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard label="Members" value={membersCount} />
        <StatCard label="Workflows" value={workflows.length} />
        <StatCard label="Artifacts" value={artifacts.length} />
        <StatCard label="Approved" value={approvedCount} />
        <StatCard label="Pending review" value={pendingReviewCount} />
      </div>

      <RepositoryOverviewCards
        loading={ctxLoading}
        repoSummary={ctxByType.get('repository_summary')}
        stack={ctxByType.get('detected_stack')}
        services={ctxByType.get('detected_services')}
        architecture={ctxByType.get('architecture_decision')}
        infra={ctxByType.get('infrastructure_summary')}
        cost={ctxByType.get('cost_summary')}
        validation={ctxByType.get('validation_summary')}
        latestWorkflow={latestWorkflow}
      />

      {latestWorkflow && (
        <WorkflowTimeline workflow={latestWorkflow} artifacts={artifacts} />
      )}
      <WorkflowPanel projectId={projectId} workflows={workflows} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <ProjectContextPanel projectId={projectId} />
        </div>
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
            Activity
          </h3>
          <ul className="rounded-xl border border-slate-200 dark:border-white/[0.06] bg-white dark:bg-surface-800/40 divide-y divide-slate-100 dark:divide-white/[0.04]">
            {workflows.slice(0, 5).map((w) => (
              <li key={w.id} className="px-3 py-2 text-xs flex items-center justify-between gap-2">
                <span className="font-mono text-slate-500 truncate">{w.id.slice(0, 8)}…</span>
                <span className="capitalize text-slate-500">{w.status}</span>
                <span className="text-slate-400 shrink-0">{timeAgo(w.created_at)}</span>
              </li>
            ))}
            {!workflows.length && (
              <li className="px-3 py-3 text-xs text-slate-500 italic">No activity yet.</li>
            )}
          </ul>
        </div>
      </div>
    </div>
  )
}

// ─── Bootstrap-aware banners ────────────────────────────────────────────────

const BOOTSTRAP_LABEL: Record<ProjectBootstrapStatus, string> = {
  pending:          'Queued',
  analyzing:        'Analyzing repository…',
  context_building: 'Building project context…',
  ready:            'Ready',
  failed:           'Analysis failed',
}

function BootstrapChip({ status }: { status: ProjectBootstrapStatus }) {
  const tone =
    status === 'ready'
      ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-500/30'
      : status === 'failed'
      ? 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-300 border-red-200 dark:border-red-500/30'
      : 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-500/30'
  return (
    <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full border', tone)}>
      <Sparkles className="w-3 h-3" /> {BOOTSTRAP_LABEL[status] ?? status}
    </span>
  )
}

function BootstrapBanner({ project }: { project: ProjectResponse }) {
  const retry = useRetryBootstrap(project.id)
  const status = project.bootstrap_status

  if (status === 'ready') return null

  if (status === 'failed') {
    return (
      <div
        className={cn(
          'p-4 rounded-xl',
          'bg-red-50 dark:bg-red-500/10',
          'border border-red-200 dark:border-red-500/30',
        )}
      >
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 shrink-0 mt-0.5" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-red-700 dark:text-red-300">
              Repository analysis failed
            </div>
            {project.bootstrap_error && (
              <pre className="text-[11px] font-mono mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words text-red-700/80 dark:text-red-300/80">
                {project.bootstrap_error.split('\n').slice(0, 6).join('\n')}
              </pre>
            )}
          </div>
          <button
            type="button"
            onClick={() => retry.mutate()}
            disabled={retry.isPending}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white shrink-0"
          >
            <RefreshCcw className={cn('w-3.5 h-3.5', retry.isPending && 'animate-spin')} />
            {retry.isPending ? 'Retrying…' : 'Retry analysis'}
          </button>
        </div>
      </div>
    )
  }

  // pending | analyzing | context_building
  const steps: ProjectBootstrapStatus[] = ['pending', 'analyzing', 'context_building', 'ready']
  const currentIdx = steps.indexOf(status)
  return (
    <div
      className={cn(
        'p-4 rounded-xl',
        'bg-brand-50/40 dark:bg-brand-600/5',
        'border border-brand-200/60 dark:border-brand-500/20',
      )}
    >
      <div className="flex items-center gap-2 text-sm font-medium text-brand-700 dark:text-brand-300">
        <Sparkles className="w-4 h-4 animate-pulse" />
        {BOOTSTRAP_LABEL[status]}
      </div>
      <ol className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-2">
        {(['analyzing', 'context_building', 'ready'] as ProjectBootstrapStatus[]).map((s, idx) => {
          const reached = currentIdx >= steps.indexOf(s)
          const active = status === s
          return (
            <li
              key={s}
              className={cn(
                'text-[11px] flex items-center gap-2 px-2 py-1.5 rounded-lg border',
                reached
                  ? 'border-brand-300/60 dark:border-brand-500/30 bg-white/40 dark:bg-brand-500/5 text-brand-700 dark:text-brand-300'
                  : 'border-slate-200 dark:border-white/[0.06] text-slate-500',
              )}
            >
              <span
                className={cn(
                  'w-1.5 h-1.5 rounded-full',
                  active
                    ? 'bg-brand-500 animate-pulse'
                    : reached
                    ? 'bg-brand-500'
                    : 'bg-slate-300 dark:bg-white/[0.08]',
                )}
              />
              {idx + 1}. {BOOTSTRAP_LABEL[s]}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

// ─── Context-driven Overview cards ──────────────────────────────────────────

function RepositoryOverviewCards({
  loading,
  repoSummary,
  stack,
  services,
  architecture,
  infra,
  cost,
  validation,
  latestWorkflow,
}: {
  loading: boolean
  repoSummary?: ProjectContextResponse
  stack?: ProjectContextResponse
  services?: ProjectContextResponse
  architecture?: ProjectContextResponse
  infra?: ProjectContextResponse
  cost?: ProjectContextResponse
  validation?: ProjectContextResponse
  latestWorkflow?: WorkflowResponse
}) {
  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="h-28 rounded-xl border border-slate-200 dark:border-white/[0.06] bg-white dark:bg-surface-800/40 animate-pulse"
          />
        ))}
      </div>
    )
  }

  if (!repoSummary && !stack && !architecture) {
    return null
  }

  const language = (repoSummary?.content.language as string) ?? '—'
  const frameworks = (stack?.content.frameworks as string[]) ?? []
  const serviceCount =
    (services?.content.services as unknown[])?.length ?? (repoSummary?.content.service_count as number) ?? 0
  const archPlans = (architecture?.content.plans as Array<{ id: string; monthly_cost?: number }>) ?? []
  const recommended = (architecture?.content.recommended_plan as string) ?? null
  const monthlyCost = cost?.content.monthly_cost as number | undefined
  const validationStatus = validation?.content.status as string | undefined
  const infraArtifactCount = (infra?.content.artifact_count as number) ?? 0

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <OverviewInfoCard
        icon={Code2Icon}
        title="Stack"
        primary={language}
        body={
          frameworks.length ? (
            <ul className="flex flex-wrap gap-1.5">
              {frameworks.slice(0, 6).map((f) => (
                <li
                  key={f}
                  className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 dark:bg-white/[0.04] text-slate-600 dark:text-slate-300"
                >
                  {f}
                </li>
              ))}
            </ul>
          ) : (
            <span className="text-xs text-slate-500 italic">No frameworks detected</span>
          )
        }
      />
      <OverviewInfoCard
        icon={Boxes}
        title="Services"
        primary={serviceCount > 0 ? `${serviceCount}` : '—'}
        body={
          <span className="text-xs text-slate-500">
            {infraArtifactCount > 0
              ? `${infraArtifactCount} infrastructure artifact(s) generated`
              : 'Detected from repository topology'}
          </span>
        }
      />
      <OverviewInfoCard
        icon={Layers}
        title="Architecture"
        primary={recommended ? capitalize(recommended) : '—'}
        body={
          <span className="text-xs text-slate-500">
            {archPlans.length > 0
              ? `${archPlans.length} strateg${archPlans.length === 1 ? 'y' : 'ies'} generated${
                  monthlyCost ? ` · $${monthlyCost.toFixed(2)}/mo` : ''
                }`
              : 'No strategies yet'}
          </span>
        }
      />
      {validationStatus && (
        <OverviewInfoCard
          icon={ShieldCheck}
          title="Validation"
          primary={capitalize(validationStatus)}
          body={
            <span className="text-xs text-slate-500">Last full run validation status</span>
          }
        />
      )}
      {latestWorkflow && (
        <OverviewInfoCard
          icon={WorkflowIcon}
          title="Latest workflow"
          primary={latestWorkflow.status}
          body={
            <span className="text-xs text-slate-500">
              {latestWorkflow.current_phase ?? 'No phase'} ·{' '}
              {timeAgo(latestWorkflow.created_at)}
            </span>
          }
        />
      )}
    </div>
  )
}

function OverviewInfoCard({
  icon: Icon,
  title,
  primary,
  body,
}: {
  icon: React.ElementType
  title: string
  primary: string
  body: React.ReactNode
}) {
  return (
    <div
      className={cn(
        'p-4 rounded-xl',
        'bg-white dark:bg-surface-800/40',
        'border border-slate-200 dark:border-white/[0.06]',
      )}
    >
      <div className="flex items-center gap-2 mb-1">
        <Icon className="w-3.5 h-3.5 text-brand-600 dark:text-brand-400" />
        <span className="text-[11px] uppercase tracking-wider text-slate-500">{title}</span>
      </div>
      <div className="text-base font-semibold text-slate-900 dark:text-white capitalize">
        {primary}
      </div>
      <div className="mt-1.5">{body}</div>
    </div>
  )
}

function capitalize(s: string) {
  if (!s) return s
  return s.charAt(0).toUpperCase() + s.slice(1)
}

// Small icon shim — FileCode2 used twice would be redundant; reuse explicitly
// so the Stack card stands apart from the Code Analysis tab icon.
const Code2Icon = FileCode2

