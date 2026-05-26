import { cn } from '@/lib/utils'
import type { ProjectRole } from '@/types/project'

const ROLE_STYLE: Record<ProjectRole, string> = {
  OWNER:           'bg-violet-50 dark:bg-violet-500/15 text-violet-700 dark:text-violet-300 border-violet-200 dark:border-violet-500/30',
  ADMIN:           'bg-red-50 dark:bg-red-500/15 text-red-700 dark:text-red-300 border-red-200 dark:border-red-500/30',
  CLOUD_ARCHITECT: 'bg-brand-50 dark:bg-brand-600/15 text-brand-700 dark:text-brand-300 border-brand-200 dark:border-brand-500/30',
  DEVELOPER:       'bg-emerald-50 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-500/30',
  VIEWER:          'bg-slate-100 dark:bg-white/[0.06] text-slate-600 dark:text-slate-300 border-slate-200 dark:border-white/[0.08]',
}

const ROLE_LABEL: Record<ProjectRole, string> = {
  OWNER: 'Owner',
  ADMIN: 'Admin',
  CLOUD_ARCHITECT: 'Cloud Architect',
  DEVELOPER: 'Developer',
  VIEWER: 'Viewer',
}

export const ROLE_OPTIONS: ProjectRole[] = ['DEVELOPER', 'CLOUD_ARCHITECT', 'VIEWER', 'ADMIN']

export function RoleBadge({ role, className }: { role: ProjectRole; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium border whitespace-nowrap',
        ROLE_STYLE[role],
        className,
      )}
    >
      {ROLE_LABEL[role]}
    </span>
  )
}

export function roleLabel(role: ProjectRole): string {
  return ROLE_LABEL[role]
}
