import { useNavigate } from 'react-router-dom'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { LogOut, User as UserIcon, ChevronDown } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { cn } from '@/lib/utils'

function initialsFrom(user: { display_name: string | null; email: string }): string {
  const source = (user.display_name || user.email).trim()
  if (!source) return '?'
  const parts = source.split(/\s+/).filter(Boolean)
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase()
  return (parts[0]![0]! + parts[1]![0]!).toUpperCase()
}

export function UserDropdown() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  if (!user) return null

  const displayName = user.display_name || user.email.split('@')[0]!
  const initials = initialsFrom(user)

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          className={cn(
            'flex items-center gap-2 pl-1.5 pr-2 py-1 rounded-lg transition-colors',
            'text-slate-700 dark:text-slate-200',
            'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
            'border border-transparent hover:border-slate-200 dark:hover:border-white/[0.08]',
            'data-[state=open]:bg-slate-100 dark:data-[state=open]:bg-white/[0.05]',
          )}
        >
          <span
            className={cn(
              'w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-semibold',
              'bg-gradient-to-br from-brand-500 to-brand-700 text-white',
            )}
          >
            {initials}
          </span>
          <span className="hidden sm:inline text-sm font-medium truncate max-w-[140px]">
            {displayName}
          </span>
          <ChevronDown className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className={cn(
            'min-w-[220px] rounded-lg overflow-hidden z-50',
            'bg-white dark:bg-surface-900',
            'border border-slate-200 dark:border-white/[0.08]',
            'shadow-lg',
            'data-[state=open]:animate-slide-in',
          )}
        >
          <div className="px-3 py-3 border-b border-slate-100 dark:border-white/[0.06]">
            <div className="text-sm font-medium text-slate-900 dark:text-white truncate">
              {displayName}
            </div>
            <div className="text-xs text-slate-500 dark:text-slate-400 truncate">
              {user.email}
            </div>
          </div>

          <div className="py-1">
            <MenuItem icon={UserIcon} label="Profile" disabled />
          </div>

          <DropdownMenu.Separator className="h-px bg-slate-100 dark:bg-white/[0.06]" />

          <div className="py-1">
            <DropdownMenu.Item
              onSelect={(e) => { e.preventDefault(); void handleLogout() }}
              className={cn(
                'flex items-center gap-2 px-3 py-2 text-sm rounded-md mx-1 cursor-pointer outline-none',
                'text-red-600 dark:text-red-400',
                'data-[highlighted]:bg-red-50 dark:data-[highlighted]:bg-red-500/10',
              )}
            >
              <LogOut className="w-4 h-4" />
              <span>Sign out</span>
            </DropdownMenu.Item>
          </div>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

function MenuItem({
  icon: Icon,
  label,
  disabled,
}: {
  icon: React.ElementType
  label: string
  disabled?: boolean
}) {
  return (
    <DropdownMenu.Item
      disabled={disabled}
      className={cn(
        'flex items-center gap-2 px-3 py-2 text-sm rounded-md mx-1 cursor-pointer outline-none',
        'text-slate-700 dark:text-slate-200',
        'data-[highlighted]:bg-slate-100 dark:data-[highlighted]:bg-white/[0.05]',
        'data-[disabled]:opacity-40 data-[disabled]:cursor-not-allowed',
      )}
    >
      <Icon className="w-4 h-4 text-slate-400 dark:text-slate-500" />
      <span>{label}</span>
      {disabled && (
        <span className="ml-auto text-[10px] uppercase tracking-wide text-slate-400 dark:text-slate-600">
          soon
        </span>
      )}
    </DropdownMenu.Item>
  )
}
