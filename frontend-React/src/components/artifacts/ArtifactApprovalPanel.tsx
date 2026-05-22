import { useState } from 'react'
import {
  CheckCircle2,
  XCircle,
  AlertCircle,
  Clock3,
  MessageSquare,
  Loader2,
  ShieldCheck,
} from 'lucide-react'
import { useCreateApproval } from '@/hooks/useProjects'
import { cn, timeAgo } from '@/lib/utils'
import type {
  ApprovalAction,
  ApprovalState,
  ArtifactApprovalResponse,
} from '@/types/project'

interface Props {
  projectId: string
  artifactId: string
  approvalState: ApprovalState
  approvals: ArtifactApprovalResponse[]
  /** True when the caller is CLOUD_ARCHITECT / ADMIN / OWNER. */
  canApprove: boolean
}

const STATE_META: Record<ApprovalState, { label: string; icon: React.ElementType; cls: string }> = {
  pending_review: {
    label: 'Pending review',
    icon: Clock3,
    cls: 'bg-slate-100 dark:bg-white/[0.04] text-slate-600 dark:text-slate-400 border-slate-200 dark:border-white/[0.06]',
  },
  approved: {
    label: 'Approved',
    icon: CheckCircle2,
    cls: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-500/30',
  },
  rejected: {
    label: 'Rejected',
    icon: XCircle,
    cls: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-300 border-red-200 dark:border-red-500/30',
  },
  requires_changes: {
    label: 'Requires changes',
    icon: AlertCircle,
    cls: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-500/30',
  },
}

export function ApprovalStateBadge({
  state,
  size = 'md',
}: {
  state: ApprovalState
  size?: 'sm' | 'md'
}) {
  const meta = STATE_META[state]
  const Icon = meta.icon
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border font-medium',
        meta.cls,
        size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-xs',
      )}
    >
      <Icon className={size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5'} />
      {meta.label}
    </span>
  )
}

export function ArtifactApprovalPanel({
  projectId,
  artifactId,
  approvalState,
  approvals,
  canApprove,
}: Props) {
  const [comment, setComment] = useState('')
  const createApproval = useCreateApproval(projectId, artifactId)

  async function submit(action: ApprovalAction) {
    if (!canApprove || createApproval.isPending) return
    await createApproval.mutateAsync({
      action,
      comment: comment.trim() || undefined,
    })
    setComment('')
  }

  return (
    <div className="space-y-3">
      <header className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-brand-600 dark:text-brand-400" />
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
            Approval workflow
          </h3>
        </div>
        <ApprovalStateBadge state={approvalState} />
      </header>

      {canApprove ? (
        <div className="rounded-xl border border-slate-200 dark:border-white/[0.06] bg-white dark:bg-surface-800/40 p-3 space-y-2">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            placeholder="Optional review comment…"
            className={cn(
              'w-full px-3 py-2 rounded-lg text-xs',
              'bg-slate-50 dark:bg-surface-900/40',
              'border border-slate-200 dark:border-white/[0.08]',
              'text-slate-900 dark:text-white',
              'placeholder:text-slate-400 dark:placeholder:text-slate-600',
              'focus:outline-none focus:ring-2 focus:ring-brand-500/40',
            )}
          />
          <div className="flex flex-wrap gap-2 justify-end">
            <ActionButton
              tone="ghost-amber"
              icon={<AlertCircle className="w-3.5 h-3.5" />}
              loading={createApproval.isPending}
              onClick={() => submit('request_changes')}
            >
              Request changes
            </ActionButton>
            <ActionButton
              tone="ghost-red"
              icon={<XCircle className="w-3.5 h-3.5" />}
              loading={createApproval.isPending}
              onClick={() => submit('reject')}
            >
              Reject
            </ActionButton>
            <ActionButton
              tone="solid-emerald"
              icon={<CheckCircle2 className="w-3.5 h-3.5" />}
              loading={createApproval.isPending}
              onClick={() => submit('approve')}
            >
              Approve
            </ActionButton>
          </div>
          {createApproval.error && (
            <div className="text-[11px] text-red-700 dark:text-red-300">
              {(createApproval.error as Error).message}
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-300 flex items-center gap-2">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          Only CLOUD_ARCHITECT, OWNER, or ADMIN may approve infrastructure
          artifacts.
        </div>
      )}

      <History approvals={approvals} />
    </div>
  )
}

function History({ approvals }: { approvals: ArtifactApprovalResponse[] }) {
  if (!approvals.length) {
    return (
      <p className="text-[11px] text-slate-500 italic">No review activity yet.</p>
    )
  }
  return (
    <ol className="space-y-2">
      {approvals.map((a) => {
        const stateForAction =
          a.action === 'approve'
            ? 'approved'
            : a.action === 'reject'
              ? 'rejected'
              : 'requires_changes'
        const meta = STATE_META[stateForAction as ApprovalState]
        const Icon = meta.icon
        return (
          <li
            key={a.id}
            className={cn(
              'rounded-lg border p-2.5 flex items-start gap-2',
              meta.cls.replace('border-', 'border-l-4 border-l-'),
              'bg-white dark:bg-surface-800/40 border-slate-200 dark:border-white/[0.06]',
            )}
          >
            <Icon className={cn('w-3.5 h-3.5 mt-0.5 shrink-0')} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] font-medium text-slate-700 dark:text-slate-300">
                  {meta.label}{' '}
                  <span className="text-slate-400 font-mono">
                    by {a.approved_by.slice(0, 8)}…
                  </span>
                </div>
                <div className="text-[10px] text-slate-400">{timeAgo(a.created_at)}</div>
              </div>
              {a.comment && (
                <div className="mt-1 flex items-start gap-1.5 text-[11px] text-slate-600 dark:text-slate-400">
                  <MessageSquare className="w-3 h-3 mt-0.5 shrink-0 text-slate-400" />
                  <span className="whitespace-pre-wrap break-words">{a.comment}</span>
                </div>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

function ActionButton({
  children,
  icon,
  onClick,
  loading,
  tone,
}: {
  children: React.ReactNode
  icon: React.ReactNode
  onClick: () => void
  loading: boolean
  tone: 'solid-emerald' | 'ghost-red' | 'ghost-amber'
}) {
  const toneCls = {
    'solid-emerald':
      'bg-emerald-600 hover:bg-emerald-500 text-white border-emerald-600',
    'ghost-red':
      'bg-white dark:bg-surface-900/40 border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-500/10',
    'ghost-amber':
      'bg-white dark:bg-surface-900/40 border-amber-200 dark:border-amber-500/30 text-amber-700 dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-500/10',
  }[tone]
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={cn(
        'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors',
        toneCls,
        'disabled:opacity-50 disabled:cursor-not-allowed',
      )}
    >
      {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : icon}
      {children}
    </button>
  )
}
