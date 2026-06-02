import { useEffect } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  Plus,
  Shield,
  ChevronLeft,
  ChevronRight,
  Cpu,
  GitBranch,
  Activity,
  Workflow,
  FolderGit2,
  Layers,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useTaskStore } from '@/store/taskStore'

const NAV = [
  { to: '/',               icon: LayoutDashboard, label: 'Dashboard'    },
  { to: '/projects',       icon: FolderGit2,      label: 'Projects'     },
  { to: '/tasks/workflow', icon: Workflow,        label: 'New Workflow' },
  { to: '/tasks/new',      icon: Plus,            label: 'Quick Task'   },
  { to: '/tasks',          icon: Activity,        label: 'All Tasks'    },
  { to: '/terraform',      icon: Layers,          label: 'Terraform'    },
]

const TOOLS = [
  { icon: Shield,    label: 'Security' },
  { icon: Cpu,       label: 'Infra' },
  { icon: GitBranch, label: 'CI/CD' },
]

export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar, mobileNavOpen, setMobileNavOpen } = useTaskStore()
  const location = useLocation()

  // Close the mobile drawer on route change so it doesn't stay parked over
  // the destination page.
  useEffect(() => {
    if (mobileNavOpen) setMobileNavOpen(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname])

  // Lock body scroll while the drawer is open.
  useEffect(() => {
    if (!mobileNavOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [mobileNavOpen])

  return (
    <>
      {/* Mobile scrim */}
      {mobileNavOpen && (
        <div
          onClick={() => setMobileNavOpen(false)}
          className="lg:hidden fixed inset-0 bg-slate-900/40 dark:bg-black/60 backdrop-blur-sm z-30"
          aria-hidden="true"
        />
      )}

      <aside
        className={cn(
          'flex flex-col shrink-0 transition-all duration-300',
          'bg-slate-50 dark:bg-surface-900',
          'border-r border-slate-200 dark:border-white/[0.06]',
          // Desktop: in-flow side column
          'lg:relative lg:h-screen',
          sidebarCollapsed ? 'lg:w-16' : 'lg:w-60',
          // Mobile: fixed drawer
          'fixed lg:translate-x-0 top-0 left-0 h-screen w-64 z-40',
          mobileNavOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        {/* Logo + mobile close */}
        <div className={cn(
          'flex items-center justify-between h-16 px-4 shrink-0',
          'border-b border-slate-200 dark:border-white/[0.06]',
        )}>
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center shrink-0">
              <Shield className="w-4 h-4 text-white" />
            </div>
            {/* Hide label only when collapsed on desktop. On mobile drawer, always show. */}
            <span className={cn(
              'font-semibold text-slate-900 dark:text-white text-sm leading-tight truncate',
              sidebarCollapsed && 'lg:hidden',
            )}>
              DevSecOps<br />
              <span className="text-brand-600 dark:text-brand-400 font-medium">AI Platform</span>
            </span>
          </div>

          {/* Close button (mobile only) */}
          <button
            onClick={() => setMobileNavOpen(false)}
            className={cn(
              'lg:hidden p-1.5 rounded-md transition-colors',
              'text-slate-400 hover:text-slate-700 dark:hover:text-white',
              'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
            )}
            aria-label="Close menu"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
          <NavSection label="Navigation" collapsed={sidebarCollapsed} />
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors group',
                  isActive
                    ? 'bg-brand-50 dark:bg-brand-600/20 text-brand-700 dark:text-brand-400 border border-brand-200 dark:border-brand-500/20'
                    : cn(
                        'border border-transparent',
                        'text-slate-600 dark:text-slate-400',
                        'hover:text-slate-900 dark:hover:text-white',
                        'hover:bg-slate-100 dark:hover:bg-white/[0.05]'
                      )
                )
              }
            >
              {({ isActive }) => (
                <>
                  <Icon
                    className={cn(
                      'w-4 h-4 shrink-0',
                      isActive ? 'text-brand-600 dark:text-brand-400' : ''
                    )}
                  />
                  <span className={cn(
                    'truncate',
                    // Collapsed-desktop: hide label. Mobile drawer: always show.
                    sidebarCollapsed && 'lg:hidden',
                  )}>
                    {label}
                  </span>
                </>
              )}
            </NavLink>
          ))}

          <div className="pt-4">
            <NavSection label="Agents" collapsed={sidebarCollapsed} />
            {TOOLS.map(({ icon: Icon, label }) => (
              <button
                key={label}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-slate-400 dark:text-slate-500 cursor-default opacity-50"
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span className={cn(
                  'truncate',
                  sidebarCollapsed && 'lg:hidden',
                )}>
                  {label}
                </span>
              </button>
            ))}
          </div>
        </nav>

        {/* Desktop-only collapse toggle */}
        <button
          onClick={toggleSidebar}
          className={cn(
            'hidden lg:flex items-center justify-center h-10 mx-3 mb-4 rounded-lg transition-colors',
            'border border-slate-200 dark:border-white/[0.06]',
            'text-slate-400 dark:text-slate-500',
            'hover:text-slate-700 dark:hover:text-white',
            'hover:border-slate-300 dark:hover:border-white/10',
            'hover:bg-slate-100 dark:hover:bg-white/[0.03]'
          )}
        >
          {sidebarCollapsed
            ? <ChevronRight className="w-4 h-4" />
            : <ChevronLeft  className="w-4 h-4" />}
        </button>
      </aside>
    </>
  )
}

function NavSection({ label, collapsed }: { label: string; collapsed: boolean }) {
  return (
    <>
      <p className={cn(
        'px-3 pb-1 text-xs font-medium text-slate-400 dark:text-slate-600 uppercase tracking-wider',
        // On collapsed desktop only, replace with a divider
        collapsed && 'lg:hidden',
      )}>
        {label}
      </p>
      {collapsed && (
        <div className="hidden lg:block border-t border-slate-200 dark:border-white/[0.06] my-2" />
      )}
    </>
  )
}
