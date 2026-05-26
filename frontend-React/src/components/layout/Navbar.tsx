import { Link } from 'react-router-dom'
import { Plus, Bell, Activity, Sun, Moon, Menu } from 'lucide-react'
import { useThemeStore } from '@/store/themeStore'
import { useTaskStore } from '@/store/taskStore'
import { cn } from '@/lib/utils'
import { UserDropdown } from './UserDropdown'

function ThemeToggle() {
  const { theme, toggle } = useThemeStore()
  const isDark = theme === 'dark'

  return (
    <button
      onClick={toggle}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      className={cn(
        'relative p-2 rounded-lg transition-colors duration-200 group',
        'text-slate-500 dark:text-slate-400',
        'hover:text-slate-900 dark:hover:text-white',
        'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
        'border border-transparent hover:border-slate-200 dark:hover:border-white/[0.08]'
      )}
    >
      <Sun
        className={cn(
          'w-4 h-4 absolute inset-0 m-auto transition-all duration-300',
          isDark
            ? 'opacity-100 rotate-0 scale-100'
            : 'opacity-0 rotate-90 scale-50 pointer-events-none'
        )}
      />
      <Moon
        className={cn(
          'w-4 h-4 transition-all duration-300',
          isDark
            ? 'opacity-0 -rotate-90 scale-50'
            : 'opacity-100 rotate-0 scale-100'
        )}
      />
    </button>
  )
}

// Placeholder bell — Part 9 will wire real notifications.
function NotificationsButton() {
  return (
    <button
      aria-label="Notifications"
      title="Notifications (coming soon)"
      className={cn(
        'relative p-2 rounded-lg transition-colors',
        'text-slate-500 dark:text-slate-400',
        'hover:text-slate-900 dark:hover:text-white',
        'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
        'border border-transparent hover:border-slate-200 dark:hover:border-white/[0.08]',
      )}
    >
      <Bell className="w-4 h-4" />
    </button>
  )
}

export function Navbar() {
  const setMobileNavOpen = useTaskStore((s) => s.setMobileNavOpen)

  return (
    <header className={cn(
      'h-16 flex items-center justify-between gap-3 px-4 sm:px-6 shrink-0',
      'border-b border-slate-200 dark:border-white/[0.06]',
      'bg-white/80 dark:bg-surface-900/80 backdrop-blur',
      'transition-colors duration-250'
    )}>
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={() => setMobileNavOpen(true)}
          aria-label="Open menu"
          className={cn(
            'lg:hidden p-2 rounded-lg transition-colors',
            'text-slate-500 dark:text-slate-400',
            'hover:text-slate-900 dark:hover:text-white',
            'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
          )}
        >
          <Menu className="w-4 h-4" />
        </button>
        <div className="hidden sm:flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
          <Activity className="w-4 h-4 text-emerald-500 dark:text-emerald-400 animate-pulse" />
          <span>API connected</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <ThemeToggle />
        <NotificationsButton />

        <Link
          to="/tasks/new"
          className="hidden sm:flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Task
        </Link>

        <div className="ml-1">
          <UserDropdown />
        </div>
      </div>
    </header>
  )
}
