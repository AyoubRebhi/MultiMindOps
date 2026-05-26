import { useMemo } from 'react'
import {
  Boxes,
  Code2,
  Database,
  FileCode2,
  FileSearch,
  GitBranch,
  Globe,
  Layers,
  Network,
  Server,
} from 'lucide-react'
import { useProjectContext } from '@/hooks/useProjects'
import { EmptyState } from '@/components/common/EmptyState'
import { Skeleton } from '@/components/common/Skeleton'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { cn, timeAgo } from '@/lib/utils'
import type { ProjectContextResponse } from '@/types/project'

interface Props {
  projectId: string
}

interface ApplicationProfile {
  application_type?: string
  workload_profile?: string
  statefulness?: string
  scalability_level?: string
  architecture_pattern?: string
  detected_services?: string[]
  entrypoints?: string[]
}

interface RepositorySummary {
  language?: string | null
  frameworks?: string[]
  build_systems?: string[]
  service_count?: number
  lines_of_code?: number | null
  has_dockerfile?: boolean
  has_compose?: boolean
  has_ci?: boolean
  application_profile?: ApplicationProfile | null
}

interface DetectedStack {
  language?: string | null
  runtime?: string | null
  frameworks?: string[]
  dependencies?: Array<string | { name?: string; version?: string }>
}

interface DetectedServices {
  services?: Array<string | { name?: string; type?: string; path?: string }>
}

/**
 * Reads ProjectContext rows (NOT artifacts) and renders the codebase
 * analysis. The backend writes analysis output as ProjectContext digests
 * via ProjectContextService._digest_repo_summary / _digest_detected_stack /
 * _digest_detected_services — so this is the canonical source.
 */
export function CodeAnalysisPanel({ projectId }: Props) {
  const { data, isLoading, error } = useProjectContext(projectId)

  const byType = useMemo(() => {
    const map = new Map<string, ProjectContextResponse>()
    for (const row of data ?? []) map.set(row.context_type, row)
    return map
  }, [data])

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-40 rounded-xl" />
        ))}
      </div>
    )
  }

  if (error) {
    return <ErrorAlert title="Failed to load analysis" message={error.message} />
  }

  const repoCtx     = byType.get('repository_summary')
  const stackCtx    = byType.get('detected_stack')
  const servicesCtx = byType.get('detected_services')

  if (!repoCtx && !stackCtx && !servicesCtx) {
    return (
      <EmptyState
        icon={FileSearch}
        title="No analysis yet"
        description="Run the ANALYSIS phase from the Workflows tab. Repository topology, detected stack, and discovered services will appear here."
      />
    )
  }

  const repo = (repoCtx?.content ?? {}) as RepositorySummary
  const stack = (stackCtx?.content ?? {}) as DetectedStack
  const services = (servicesCtx?.content ?? {}) as DetectedServices
  const profile = repo.application_profile ?? null

  return (
    <div className="space-y-5">
      {/* Top: KPI strip from repo_summary */}
      {repoCtx && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KpiTile
            icon={Code2}
            label="Language"
            value={repo.language || '—'}
          />
          <KpiTile
            icon={Boxes}
            label="Services"
            value={String(repo.service_count ?? 0)}
          />
          <KpiTile
            icon={FileCode2}
            label="Lines of code"
            value={repo.lines_of_code ? repo.lines_of_code.toLocaleString() : '—'}
          />
          <KpiTile
            icon={GitBranch}
            label="Build artifacts"
            value={[
              repo.has_dockerfile && 'Dockerfile',
              repo.has_compose && 'Compose',
              repo.has_ci && 'CI',
            ].filter(Boolean).join(', ') || 'None'}
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Application profile */}
        {profile && (
          <Card
            title="Application profile"
            icon={Layers}
            subtitle={`Detected by ${repoCtx?.generated_by ?? 'OrchestratorAgent'} · ${
              repoCtx?.updated_at ? timeAgo(repoCtx.updated_at) : ''
            }`}
          >
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs">
              {profile.application_type && <Row label="Type" value={prettify(profile.application_type)} />}
              {profile.architecture_pattern && <Row label="Pattern" value={prettify(profile.architecture_pattern)} />}
              {profile.workload_profile && <Row label="Workload" value={prettify(profile.workload_profile)} />}
              {profile.statefulness && <Row label="State" value={prettify(profile.statefulness)} />}
              {profile.scalability_level && <Row label="Scalability" value={prettify(profile.scalability_level)} />}
            </dl>

            {(profile.detected_services?.length ?? 0) > 0 && (
              <div className="mt-4">
                <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1.5">
                  Components
                </div>
                <ul className="flex flex-wrap gap-1.5">
                  {profile.detected_services!.map((svc) => (
                    <ServiceChip key={svc} name={svc} />
                  ))}
                </ul>
              </div>
            )}

            {(profile.entrypoints?.length ?? 0) > 0 && (
              <div className="mt-4">
                <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1.5">
                  Entrypoints
                </div>
                <ul className="space-y-1">
                  {profile.entrypoints!.map((ep) => (
                    <li
                      key={ep}
                      className="text-[11px] font-mono text-slate-600 dark:text-slate-400 break-all"
                    >
                      <span className="text-slate-300 dark:text-slate-700 mr-1.5">›</span>
                      {ep}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>
        )}

        {/* Detected stack */}
        {stackCtx && (
          <Card
            title="Detected stack"
            icon={Code2}
            subtitle={`${stackCtx.generated_by ?? 'OrchestratorAgent'} · ${timeAgo(stackCtx.updated_at)}`}
          >
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs">
              <Row label="Language" value={stack.language || '—'} />
              <Row label="Runtime"  value={stack.runtime  || '—'} />
            </dl>
            {(stack.frameworks?.length ?? 0) > 0 ? (
              <div className="mt-4">
                <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1.5">
                  Frameworks
                </div>
                <ul className="flex flex-wrap gap-1.5">
                  {stack.frameworks!.map((fw) => (
                    <li
                      key={fw}
                      className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/30"
                    >
                      {fw}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="mt-4 text-xs text-slate-500 italic">No frameworks detected.</p>
            )}
            {(stack.dependencies?.length ?? 0) > 0 && (
              <p className="mt-3 text-[11px] text-slate-400">
                {stack.dependencies!.length} dependenc{stack.dependencies!.length === 1 ? 'y' : 'ies'} indexed
              </p>
            )}
          </Card>
        )}

        {/* Detected services */}
        {servicesCtx && (
          <Card
            title="Detected services"
            icon={Boxes}
            subtitle={`${servicesCtx.generated_by ?? 'OrchestratorAgent'} · ${timeAgo(servicesCtx.updated_at)}`}
          >
            {(services.services?.length ?? 0) === 0 ? (
              <p className="text-xs text-slate-500 italic">
                No services discovered. The analyzer infers services from compose
                files, manifests, and module entrypoints — none were detected in
                this repository.
              </p>
            ) : (
              <ul className="space-y-2">
                {services.services!.map((svc, idx) => {
                  const name = typeof svc === 'string' ? svc : svc.name ?? '(unnamed)'
                  const type = typeof svc === 'string' ? null : svc.type
                  const path = typeof svc === 'string' ? null : svc.path
                  return (
                    <li
                      key={`${name}-${idx}`}
                      className={cn(
                        'flex items-start gap-3 p-2.5 rounded-lg',
                        'bg-slate-50 dark:bg-white/[0.03]',
                        'border border-slate-200 dark:border-white/[0.06]',
                      )}
                    >
                      <ServiceIcon name={name} />
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-medium text-slate-800 dark:text-slate-200">
                          {prettify(name)}
                        </div>
                        {(type || path) && (
                          <div className="text-[11px] text-slate-500 dark:text-slate-500 mt-0.5 truncate">
                            {type && <span>{type}</span>}
                            {type && path && <span> · </span>}
                            {path && <span className="font-mono">{path}</span>}
                          </div>
                        )}
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </Card>
        )}

        {/* Build systems (from repo_summary) */}
        {(repo.build_systems?.length ?? 0) > 0 && (
          <Card
            title="Build systems"
            icon={GitBranch}
            subtitle="Inferred from repository scan"
          >
            <ul className="flex flex-wrap gap-1.5">
              {repo.build_systems!.map((bs) => (
                <li
                  key={bs}
                  className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 dark:bg-white/[0.06] text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-white/[0.08]"
                >
                  {bs}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </div>
  )
}

// ─── Small building blocks ──────────────────────────────────────────────────

function Card({
  title,
  subtitle,
  icon: Icon,
  children,
}: {
  title: string
  subtitle?: string
  icon: React.ElementType
  children: React.ReactNode
}) {
  return (
    <section className={cn(
      'p-4 rounded-xl',
      'bg-white dark:bg-surface-800/40',
      'border border-slate-200 dark:border-white/[0.06]',
    )}>
      <header className="flex items-start gap-2.5 mb-3">
        <div className="p-1.5 rounded-md bg-brand-50 dark:bg-brand-600/15">
          <Icon className="w-3.5 h-3.5 text-brand-600 dark:text-brand-400" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">{title}</h3>
          {subtitle && (
            <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-0.5">{subtitle}</p>
          )}
        </div>
      </header>
      {children}
    </section>
  )
}

function KpiTile({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ElementType
  label: string
  value: string
}) {
  return (
    <div className={cn(
      'p-3 rounded-xl',
      'bg-white dark:bg-surface-800/40',
      'border border-slate-200 dark:border-white/[0.06]',
    )}>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-400 mb-1">
        <Icon className="w-3 h-3" />
        {label}
      </div>
      <div className="text-sm font-semibold text-slate-900 dark:text-white truncate">{value}</div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-slate-500 dark:text-slate-500">{label}</dt>
      <dd className="text-slate-800 dark:text-slate-200 font-medium truncate">{value}</dd>
    </>
  )
}

function ServiceChip({ name }: { name: string }) {
  return (
    <li
      className={cn(
        'inline-flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded-full',
        'bg-brand-50 dark:bg-brand-600/15 text-brand-700 dark:text-brand-300',
        'border border-brand-200 dark:border-brand-500/30',
      )}
    >
      <ServiceIcon name={name} small />
      {prettify(name)}
    </li>
  )
}

function ServiceIcon({ name, small }: { name: string; small?: boolean }) {
  const n = name.toLowerCase()
  const cls = small ? 'w-3 h-3' : 'w-4 h-4'
  if (/(postgres|mysql|mongo|sqlite|maria|cassandra)/.test(n))
    return <Database className={cn(cls, 'text-blue-500')} />
  if (/(redis|memcache)/.test(n))
    return <Database className={cn(cls, 'text-rose-500')} />
  if (/(front|web|ui|react|vue|angular|svelte)/.test(n))
    return <Globe className={cn(cls, 'text-emerald-500')} />
  if (/(api|backend|service|server)/.test(n))
    return <Server className={cn(cls, 'text-amber-500')} />
  if (/(queue|broker|kafka|rabbit|nats)/.test(n))
    return <Network className={cn(cls, 'text-violet-500')} />
  return <Boxes className={cn(cls, 'text-slate-400')} />
}

function prettify(s: string): string {
  if (!s) return s
  return s
    .split(/[-_]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}
