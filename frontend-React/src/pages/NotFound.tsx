import { Link } from 'react-router-dom'
import { Shield, ArrowLeft } from 'lucide-react'
import { cn } from '@/lib/utils'

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-6 py-24 text-center px-4">
      <div className={cn(
        'w-16 h-16 rounded-2xl flex items-center justify-center',
        'bg-slate-100 dark:bg-surface-800/60',
        'border border-slate-200 dark:border-white/[0.06]'
      )}>
        <Shield className="w-8 h-8 text-slate-300 dark:text-slate-600" />
      </div>

      <div>
        <h1 className="text-4xl font-bold text-slate-900 dark:text-white mb-2">404</h1>
        <p className="text-slate-500">Page not found</p>
      </div>

      <Link
        to="/"
        className={cn(
          'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
          'bg-brand-50 dark:bg-brand-600/20',
          'hover:bg-brand-100 dark:hover:bg-brand-600/30',
          'text-brand-700 dark:text-brand-300',
          'border border-brand-200 dark:border-brand-500/20'
        )}
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Dashboard
      </Link>
    </div>
  )
}
