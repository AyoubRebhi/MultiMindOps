import { Link } from 'react-router-dom'
import { Plus, Github, Activity } from 'lucide-react'

export function Navbar() {
  return (
    <header className="h-16 border-b border-white/[0.06] bg-surface-900/80 backdrop-blur flex items-center justify-between px-6 shrink-0">
      <div className="flex items-center gap-2 text-sm text-slate-400">
        <Activity className="w-4 h-4 text-emerald-400 animate-pulse" />
        <span>API connected</span>
      </div>

      <div className="flex items-center gap-3">
        <a
          href="https://github.com"
          target="_blank"
          rel="noreferrer"
          className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-white/[0.05] transition-colors"
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
