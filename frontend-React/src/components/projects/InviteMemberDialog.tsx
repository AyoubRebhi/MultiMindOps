import { useState, type FormEvent } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X, UserPlus, Info } from 'lucide-react'
import { useAddProjectMember } from '@/hooks/useProjects'
import { useToast } from '@/components/common/Toast'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ROLE_OPTIONS, roleLabel } from './RoleBadge'
import { cn } from '@/lib/utils'
import type { ProjectRole } from '@/types/project'

interface Props {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * Add a member by user ID + role.
 *
 * Backend caveat: there is no invite-by-email endpoint yet. The form
 * accepts a UUID directly so the platform admin can wire up a new user
 * by hand until /api/projects/{id}/invites lands.
 */
export function InviteMemberDialog({ projectId, open, onOpenChange }: Props) {
  const [userId, setUserId] = useState('')
  const [role, setRole] = useState<ProjectRole>('DEVELOPER')
  const [error, setError] = useState<string | null>(null)
  const addMember = useAddProjectMember(projectId)
  const toast = useToast()

  const reset = () => {
    setUserId('')
    setRole('DEVELOPER')
    setError(null)
  }

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    const trimmed = userId.trim()
    if (!trimmed) {
      setError('User ID is required')
      return
    }
    try {
      await addMember.mutateAsync({ user_id: trimmed, role })
      toast.success('Member added', `${roleLabel(role)} access granted.`)
      reset()
      onOpenChange(false)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to add member'
      setError(message)
    }
  }

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o)
        if (!o) reset()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-slate-900/40 dark:bg-black/60 backdrop-blur-sm z-50 data-[state=open]:animate-in data-[state=open]:fade-in" />
        <Dialog.Content
          className={cn(
            'fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50',
            'w-[480px] max-w-[calc(100vw-2rem)] max-h-[85vh] overflow-auto',
            'bg-white dark:bg-surface-900 rounded-xl shadow-xl',
            'border border-slate-200 dark:border-white/[0.08]',
            'data-[state=open]:animate-slide-in',
          )}
        >
          <div className="flex items-start justify-between p-5 border-b border-slate-100 dark:border-white/[0.06]">
            <div className="flex items-start gap-3">
              <div className="p-2 rounded-lg bg-brand-50 dark:bg-brand-600/15">
                <UserPlus className="w-4 h-4 text-brand-600 dark:text-brand-400" />
              </div>
              <div>
                <Dialog.Title className="text-base font-semibold text-slate-900 dark:text-white">
                  Add member
                </Dialog.Title>
                <Dialog.Description className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                  Grant a user role-based access to this project.
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors">
              <X className="w-4 h-4" />
            </Dialog.Close>
          </div>

          <form onSubmit={onSubmit} className="p-5 space-y-4">
            <div className={cn(
              'flex gap-2 p-3 rounded-lg text-xs',
              'bg-slate-50 dark:bg-white/[0.03]',
              'border border-slate-200 dark:border-white/[0.06]',
              'text-slate-600 dark:text-slate-400',
            )}>
              <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-slate-400" />
              <p>
                Invite-by-email is coming soon. For now, add an existing user by
                their user ID (UUID).
              </p>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1.5">
                User ID
              </label>
              <input
                type="text"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                placeholder="00000000-0000-0000-0000-000000000000"
                className={cn(
                  'w-full px-3 py-2 rounded-lg text-sm font-mono transition-colors',
                  'bg-white dark:bg-surface-900',
                  'border border-slate-200 dark:border-white/[0.08]',
                  'text-slate-900 dark:text-white placeholder:text-slate-300 dark:placeholder:text-slate-600',
                  'focus:outline-none focus:border-brand-500 dark:focus:border-brand-400 focus:ring-2 focus:ring-brand-500/20',
                )}
                disabled={addMember.isPending}
                autoFocus
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1.5">
                Role
              </label>
              <div className="grid grid-cols-2 gap-2">
                {ROLE_OPTIONS.map((opt) => (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => setRole(opt)}
                    className={cn(
                      'px-3 py-2 rounded-lg text-xs font-medium text-left transition-colors',
                      'border',
                      role === opt
                        ? 'bg-brand-50 dark:bg-brand-600/15 border-brand-300 dark:border-brand-500/40 text-brand-700 dark:text-brand-300'
                        : 'bg-white dark:bg-surface-900 border-slate-200 dark:border-white/[0.08] text-slate-600 dark:text-slate-400 hover:border-slate-300 dark:hover:border-white/[0.15]',
                    )}
                    disabled={addMember.isPending}
                  >
                    {roleLabel(opt)}
                  </button>
                ))}
              </div>
            </div>

            {error && (
              <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
            )}

            <div className="flex items-center justify-end gap-2 pt-2">
              <Dialog.Close
                className={cn(
                  'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                  'text-slate-600 dark:text-slate-300',
                  'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
                )}
                disabled={addMember.isPending}
              >
                Cancel
              </Dialog.Close>
              <button
                type="submit"
                disabled={addMember.isPending || !userId.trim()}
                className={cn(
                  'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                  'bg-brand-600 hover:bg-brand-500 text-white',
                  'disabled:opacity-50 disabled:cursor-not-allowed',
                )}
              >
                {addMember.isPending ? (
                  <>
                    <LoadingSpinner className="w-3.5 h-3.5 text-white" />
                    Adding…
                  </>
                ) : (
                  <>
                    <UserPlus className="w-3.5 h-3.5" />
                    Add member
                  </>
                )}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
