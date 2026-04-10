import { Link } from 'react-router-dom'
import { Plus, Github, Activity, Sun, Moon } from 'lucide-react'
import { useThemeStore } from '@/store/themeStore'
import { cn } from '@/lib/utils'

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
      {/* Sun (shown in dark mode — click to go light) */}
      <Sun
        className={cn(
          'w-4 h-4 absolute inset-0 m-auto transition-all duration-300',
          isDark
            ? 'opacity-100 rotate-0 scale-100'
            : 'opacity-0 rotate-90 scale-50 pointer-events-none'
        )}
      />
      {/* Moon (shown in light mode — click to go dark) */}
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

export function Navbar() {
  return (
    <header className={cn(
      'h-16 flex items-center justify-between px-6 shrink-0',
      'border-b border-slate-200 dark:border-white/[0.06]',
      'bg-white/80 dark:bg-surface-900/80 backdrop-blur',
      'transition-colors duration-250'
    )}>
      <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
        <Activity className="w-4 h-4 text-emerald-500 dark:text-emerald-400 animate-pulse" />
        <span>API connected</span>
      </div>

      <div className="flex items-center gap-2">
        <ThemeToggle />

        <a
          href="https://github.com"
          target="_blank"
          rel="noreferrer"
          className={cn(
            'p-2 rounded-lg transition-colors',
            'text-slate-500 dark:text-slate-400',
            'hover:text-slate-900 dark:hover:text-white',
            'hover:bg-slate-100 dark:hover:bg-white/[0.05]'
          )}
        >
          <Github className="w-4 h-4" />
        </a>

        <Link
          to="/tasks/new"
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Task
        </Link>
      </div>
    </header>
  )
}
