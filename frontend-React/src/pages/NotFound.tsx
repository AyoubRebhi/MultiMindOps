import { Link } from 'react-router-dom'
import { Shield, ArrowLeft } from 'lucide-react'

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-6 py-24 text-center px-4">
      <div className="w-16 h-16 rounded-2xl bg-surface-800/60 border border-white/[0.06] flex items-center justify-center">
        <Shield className="w-8 h-8 text-slate-600" />
      </div>
      <div>
        <h1 className="text-4xl font-bold text-white mb-2">404</h1>
        <p className="text-slate-500">Page not found</p>
      </div>
      <Link
        to="/"
        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-600/20 hover:bg-brand-600/30 text-brand-300 text-sm font-medium transition-colors border border-brand-500/20"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Dashboard
      </Link>
    </div>
  )
}
