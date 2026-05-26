import { Link } from 'react-router-dom'
import { ShieldAlert, ArrowLeft } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { cn } from '@/lib/utils'

export default function UnauthorizedPage() {
  const { isAuthenticated, logout } = useAuth()

  return (
    <div className="min-h-screen flex items-center justify-center bg-white dark:bg-surface-950 px-6">
      <div className={cn(
        'max-w-md w-full p-8 rounded-2xl text-center',
        'bg-white dark:bg-surface-900',
        'border border-slate-200 dark:border-white/[0.06]',
        'shadow-sm',
      )}>
        <div className="mx-auto w-14 h-14 rounded-xl bg-amber-50 dark:bg-amber-500/10 flex items-center justify-center mb-5">
          <ShieldAlert className="w-7 h-7 text-amber-600 dark:text-amber-400" />
        </div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-white">
          You don't have access to this page
        </h1>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Your account doesn't have permission to view this resource. If you
          think this is a mistake, contact your workspace administrator.
        </p>

        <div className="mt-6 flex items-center justify-center gap-3">
          <Link
            to="/"
            className={cn(
              'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              'bg-brand-600 hover:bg-brand-500 text-white',
            )}
          >
            <ArrowLeft className="w-4 h-4" />
            Back to dashboard
          </Link>
          {isAuthenticated && (
            <button
              onClick={() => { void logout() }}
              className={cn(
                'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                'text-slate-600 dark:text-slate-300',
                'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
                'border border-slate-200 dark:border-white/[0.08]',
              )}
            >
              Sign out
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
