import { useEffect, useMemo, useState } from 'react'
import { FileCode2, History } from 'lucide-react'
import { useArtifactDetail, useProjectRole } from '@/hooks/useProjects'
import { cn, timeAgo } from '@/lib/utils'
import type { ApprovalState, ArtifactResponse } from '@/types/project'
import {
  ApprovalStateBadge,
  ArtifactApprovalPanel,
} from '@/components/artifacts/ArtifactApprovalPanel'

const APPROVER_ROLES = new Set(['CLOUD_ARCHITECT', 'OWNER', 'ADMIN'])

interface Props {
  projectId: string
  artifacts: ArtifactResponse[]
  emptyMessage?: string
}

/**
 * Two-pane viewer: file list on the left, content (with version dropdown)
 * on the right. Selection persists locally — no router state.
 */
export function ArtifactViewer({ projectId, artifacts, emptyMessage }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(artifacts[0]?.id ?? null)

  // Keep selection valid when the artifacts list changes (e.g. after rerun).
  useEffect(() => {
    if (selectedId && !artifacts.some((a) => a.id === selectedId)) {
      setSelectedId(artifacts[0]?.id ?? null)
    } else if (!selectedId && artifacts.length > 0) {
      setSelectedId(artifacts[0].id)
    }
  }, [artifacts, selectedId])

  if (!artifacts.length) {
    return (
      <div
        className={cn(
          'p-6 rounded-xl text-center',
          'border border-dashed border-slate-200 dark:border-white/[0.08]',
        )}
      >
        <FileCode2 className="w-8 h-8 mx-auto text-slate-300 dark:text-slate-700 mb-3" />
        <p className="text-sm text-slate-500">
          {emptyMessage ?? 'No artifacts yet. Run the relevant phase to generate them.'}
        </p>
      </div>
    )
  }

  return (
    <div
      className={cn(
        'grid grid-cols-1 md:grid-cols-[240px_1fr] rounded-xl overflow-hidden',
        'bg-white dark:bg-surface-800/40',
        'border border-slate-200 dark:border-white/[0.06]',
      )}
    >
      <ul className="border-r border-slate-200 dark:border-white/[0.06] max-h-[480px] overflow-y-auto">
        {artifacts.map((a) => (
          <li key={a.id}>
            <button
              onClick={() => setSelectedId(a.id)}
              className={cn(
                'w-full text-left px-3 py-2 text-xs transition-colors flex items-center justify-between gap-2',
                'border-b last:border-0 border-slate-100 dark:border-white/[0.04]',
                selectedId === a.id
                  ? 'bg-brand-50 dark:bg-brand-600/15 text-brand-700 dark:text-brand-300'
                  : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-white/[0.03]',
              )}
            >
              <span className="truncate font-mono">{a.artifact_subtype}</span>
              <span className="flex items-center gap-1 shrink-0">
                <ApprovalStateBadge state={a.approval_state} size="sm" />
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-white/[0.04]">
                  v{a.version}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>

      <div className="min-w-0">
        {selectedId ? (
          <ArtifactContent projectId={projectId} artifactId={selectedId} />
        ) : (
          <div className="p-6 text-center text-xs text-slate-500">Select a file</div>
        )}
      </div>
    </div>
  )
}

function ArtifactContent({ projectId, artifactId }: { projectId: string; artifactId: string }) {
  const { data, isLoading, error } = useArtifactDetail(projectId, artifactId)
  const role = useProjectRole(projectId)
  const canApprove = !!role && APPROVER_ROLES.has(role)
  const [version, setVersion] = useState<number | null>(null)

  useEffect(() => {
    setVersion(null)
  }, [artifactId])

  const content = useMemo(() => {
    if (!data) return ''
    if (version == null || version === data.version) return data.content
    const v = data.versions.find((x) => x.version === version)
    return v?.content ?? data.content
  }, [data, version])

  if (isLoading) return <div className="p-6 text-xs text-slate-500">Loading…</div>
  if (error)
    return (
      <div className="p-6 text-xs text-red-600 dark:text-red-400">
        Failed to load artifact: {error.message}
      </div>
    )
  if (!data) return null

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-200 dark:border-white/[0.06]">
        <div className="min-w-0">
          <div className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate">
            {data.artifact_subtype}
          </div>
          <div className="text-[10px] text-slate-400 mt-0.5">
            {data.generated_by_agent ?? 'unknown agent'} · updated {timeAgo(data.updated_at)}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span
            className={cn(
              'text-[10px] px-2 py-0.5 rounded-full border',
              data.validation_status === 'passed'
                ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-500/20'
                : data.validation_status === 'failed'
                  ? 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-300 border-red-200 dark:border-red-500/20'
                  : 'bg-slate-100 dark:bg-white/[0.04] text-slate-600 dark:text-slate-400 border-slate-200 dark:border-white/[0.06]',
            )}
          >
            {data.validation_status}
          </span>
          {data.versions.length > 1 && (
            <label className="flex items-center gap-1 text-[11px] text-slate-500">
              <History className="w-3 h-3" />
              <select
                value={version ?? data.version}
                onChange={(e) => setVersion(Number(e.target.value))}
                className="bg-transparent border border-slate-200 dark:border-white/[0.08] rounded px-1.5 py-0.5"
              >
                {data.versions.map((v) => (
                  <option key={v.version} value={v.version}>
                    v{v.version} ({timeAgo(v.created_at)})
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </div>
      <pre className="p-4 text-xs font-mono text-slate-700 dark:text-slate-300 overflow-auto max-h-[420px] whitespace-pre-wrap break-words">
        {content}
      </pre>

      <div className="px-3 py-3 border-t border-slate-200 dark:border-white/[0.06]">
        <ArtifactApprovalPanel
          projectId={projectId}
          artifactId={data.id}
          approvalState={(data.approval_state ?? 'pending_review') as ApprovalState}
          approvals={data.approvals ?? []}
          canApprove={canApprove}
        />
      </div>
    </div>
  )
}
