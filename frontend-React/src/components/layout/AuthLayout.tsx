import { Outlet } from 'react-router-dom'
import { Shield } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Shell for unauthenticated routes (/login, /register).
 *
 * Two-column split on desktop: marketing left rail + form panel right.
 * Collapses to single-column form on small viewports.
 */
export function AuthLayout() {
  return (
    <div className="min-h-screen flex flex-col lg:flex-row bg-white dark:bg-surface-950">
      {/* Brand rail */}
      <aside
        className={cn(
          'hidden lg:flex flex-col justify-between w-1/2 xl:w-5/12 p-12',
          'bg-gradient-to-br from-brand-600 via-brand-700 to-surface-900',
          'text-white relative overflow-hidden',
        )}
      >
        <div className="relative z-10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-white/10 backdrop-blur flex items-center justify-center">
              <Shield className="w-5 h-5 text-white" />
            </div>
            <span className="font-semibold text-lg leading-tight">
              DevSecOps
              <span className="block text-sm font-medium opacity-80">AI Platform</span>
            </span>
          </div>
        </div>

        <div className="relative z-10 space-y-4 max-w-md">
          <h2 className="text-3xl font-bold leading-tight">
            Ship secure infrastructure, faster.
          </h2>
          <p className="text-white/80 text-sm leading-relaxed">
            From a single prompt to production — AI-generated Dockerfiles,
            Terraform, and Kubernetes manifests, reviewed by your team and
            executed in a governed pipeline.
          </p>
          <ul className="space-y-2 pt-2 text-sm text-white/80">
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-white/60" />
              Structured generation with execution-aware validators
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-white/60" />
              Approval workflows, audit trail, and role-based access
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-white/60" />
              Self-healing corrector loop on every artifact
            </li>
          </ul>
        </div>

        {/* Decorative gradient blob */}
        <div className="absolute -bottom-32 -right-32 w-96 h-96 rounded-full bg-brand-400/20 blur-3xl pointer-events-none" />
        <div className="absolute -top-24 -left-16 w-72 h-72 rounded-full bg-brand-300/10 blur-3xl pointer-events-none" />
      </aside>

      {/* Form panel */}
      <main className="flex-1 flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-md">
          {/* Mobile-only brand block */}
          <div className="lg:hidden flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center">
              <Shield className="w-5 h-5 text-white" />
            </div>
            <span className="font-semibold text-slate-900 dark:text-white">
              DevSecOps AI Platform
            </span>
          </div>
          <Outlet />
        </div>
      </main>
    </div>
  )
}
