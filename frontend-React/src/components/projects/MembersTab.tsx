import { useState } from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { ChevronDown, Lock, ShieldAlert, UserPlus, Users } from 'lucide-react'
import {
  useUpdateProjectMember,
} from '@/hooks/useProjects'
import { useToast } from '@/components/common/Toast'
import { EmptyState } from '@/components/common/EmptyState'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ROLE_OPTIONS, RoleBadge, roleLabel } from './RoleBadge'
import { InviteMemberDialog } from './InviteMemberDialog'
import { cn, timeAgo } from '@/lib/utils'
import type { ProjectMemberResponse, ProjectRole } from '@/types/project'

interface Props {
  projectId: string
  members: ProjectMemberResponse[]
  currentUserRole: ProjectRole | null
  currentUserId: string | null
}

const MANAGE_ROLES = new Set<ProjectRole>(['OWNER', 'ADMIN'])

export function MembersTab({ projectId, members, currentUserRole, currentUserId }: Props) {
  const [inviteOpen, setInviteOpen] = useState(false)
  const canManage = !!currentUserRole && MANAGE_ROLES.has(currentUserRole)

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
          <Users className="w-4 h-4" />
          <span>{members.length} member{members.length === 1 ? '' : 's'}</span>
        </div>
        {canManage ? (
          <button
            onClick={() => setInviteOpen(true)}
            className={cn(
              'inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
              'bg-brand-600 hover:bg-brand-500 text-white',
            )}
          >
            <UserPlus className="w-3.5 h-3.5" />
            Add member
          </button>
        ) : (
          <div className="inline-flex items-center gap-1.5 text-[11px] text-slate-400 dark:text-slate-500">
            <Lock className="w-3 h-3" />
            Only owners and admins can manage members
          </div>
        )}
      </div>

      {/* Members list */}
      {members.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No members yet"
          description={
            canManage
              ? 'Add the first member to start collaborating on this project.'
              : 'This project has no members yet.'
          }
          action={
            canManage ? (
              <button
                onClick={() => setInviteOpen(true)}
                className={cn(
                  'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                  'bg-brand-600 hover:bg-brand-500 text-white',
                )}
              >
                <UserPlus className="w-4 h-4" />
                Add first member
              </button>
            ) : undefined
          }
        />
      ) : (
        <ul className="space-y-2">
          {members.map((m) => (
            <MemberRow
              key={m.id}
              projectId={projectId}
              member={m}
              canManage={canManage}
              isSelf={m.user_id === currentUserId}
            />
          ))}
        </ul>
      )}

      <InviteMemberDialog
        projectId={projectId}
        open={inviteOpen}
        onOpenChange={setInviteOpen}
      />
    </div>
  )
}

// ─── Single member row ──────────────────────────────────────────────────────

function MemberRow({
  projectId,
  member,
  canManage,
  isSelf,
}: {
  projectId: string
  member: ProjectMemberResponse
  canManage: boolean
  isSelf: boolean
}) {
  const updateMember = useUpdateProjectMember(projectId)
  const toast = useToast()

  // OWNER role is structural — you can't demote the owner from this UI.
  const isOwner = member.role === 'OWNER'
  const canEdit = canManage && !isOwner && !isSelf

  const handleSelect = async (next: ProjectRole) => {
    if (next === member.role) return
    try {
      await updateMember.mutateAsync({ memberId: member.id, role: next })
      toast.success('Role updated', `${shortId(member.user_id)} is now ${roleLabel(next)}.`)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to update role'
      toast.error('Could not update role', message)
    }
  }

  return (
    <li
      className={cn(
        'flex items-center justify-between gap-3 p-3 rounded-lg',
        'bg-white dark:bg-surface-800/40',
        'border border-slate-200 dark:border-white/[0.06]',
      )}
    >
      <div className="flex items-center gap-3 min-w-0">
        <Avatar id={member.user_id} />
        <div className="min-w-0">
          <div className="text-sm font-medium text-slate-900 dark:text-white truncate">
            {shortId(member.user_id)}
            {isSelf && (
              <span className="ml-1.5 text-[10px] uppercase tracking-wide text-brand-600 dark:text-brand-400">
                you
              </span>
            )}
          </div>
          <div className="text-[11px] text-slate-400 dark:text-slate-500">
            Joined {timeAgo(member.created_at)}
          </div>
        </div>
      </div>

      {canEdit ? (
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button
              className={cn(
                'inline-flex items-center gap-1.5 px-2 py-1 rounded-md transition-colors',
                'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
              )}
              disabled={updateMember.isPending}
            >
              <RoleBadge role={member.role} />
              {updateMember.isPending ? (
                <LoadingSpinner className="w-3 h-3" />
              ) : (
                <ChevronDown className="w-3 h-3 text-slate-400" />
              )}
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="end"
              sideOffset={6}
              className={cn(
                'min-w-[200px] rounded-lg overflow-hidden z-50 py-1',
                'bg-white dark:bg-surface-900',
                'border border-slate-200 dark:border-white/[0.08]',
                'shadow-lg',
                'data-[state=open]:animate-slide-in',
              )}
            >
              {ROLE_OPTIONS.map((opt) => (
                <DropdownMenu.Item
                  key={opt}
                  onSelect={() => { void handleSelect(opt) }}
                  className={cn(
                    'flex items-center justify-between gap-3 mx-1 px-3 py-2 text-sm rounded-md cursor-pointer outline-none',
                    'data-[highlighted]:bg-slate-100 dark:data-[highlighted]:bg-white/[0.05]',
                  )}
                >
                  <span className="text-slate-700 dark:text-slate-200">{roleLabel(opt)}</span>
                  {member.role === opt && (
                    <span className="text-[10px] text-brand-600 dark:text-brand-400">current</span>
                  )}
                </DropdownMenu.Item>
              ))}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      ) : (
        <div className="flex items-center gap-2">
          <RoleBadge role={member.role} />
          {isOwner && !canManage && (
            <ShieldAlert className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
          )}
        </div>
      )}
    </li>
  )
}

function Avatar({ id }: { id: string }) {
  const initials = id.slice(0, 2).toUpperCase()
  return (
    <span className="w-9 h-9 shrink-0 rounded-full bg-gradient-to-br from-brand-500/80 to-brand-700 text-white text-xs font-semibold flex items-center justify-center">
      {initials}
    </span>
  )
}

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id
}
