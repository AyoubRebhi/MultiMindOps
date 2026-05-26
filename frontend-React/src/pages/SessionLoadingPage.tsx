import { Shield } from 'lucide-react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'

export default function SessionLoadingPage() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-white dark:bg-surface-950 gap-6">
      <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center shadow-lg">
        <Shield className="w-6 h-6 text-white" />
      </div>
      <div className="flex items-center gap-3">
        <LoadingSpinner className="w-5 h-5" />
        <span className="text-sm text-slate-500 dark:text-slate-400">Restoring your session…</span>
      </div>
    </div>
  )
}
