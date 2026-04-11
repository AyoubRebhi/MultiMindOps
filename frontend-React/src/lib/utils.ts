import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { TaskStatus } from '@/types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  }).format(new Date(iso))
}

export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60)  return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60)  return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24)  return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

export function statusMeta(status: TaskStatus): {
  label: string
  color: string
  dot: string
  pulse: boolean
} {
  switch (status) {
    case 'pending':
      return { label: 'Pending',      color: 'text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-400/10 border-slate-300 dark:border-slate-400/20',          dot: 'bg-slate-400',   pulse: false }
    case 'in_progress':
      return { label: 'Running',      color: 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-400/10 border-blue-200 dark:border-blue-400/20',                   dot: 'bg-blue-500',    pulse: true  }
    case 'completed':
      return { label: 'Completed',    color: 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-400/10 border-emerald-200 dark:border-emerald-400/20', dot: 'bg-emerald-500', pulse: false }
    case 'failed':
      return { label: 'Failed',       color: 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-400/10 border-red-200 dark:border-red-400/20',                         dot: 'bg-red-500',     pulse: false }
    case 'awaiting_human_review':
      return { label: 'Needs Review', color: 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-400/10 border-amber-200 dark:border-amber-400/20',             dot: 'bg-amber-500',   pulse: true  }
    case 'human_approved':
      return { label: 'Approved',     color: 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-400/10 border-emerald-200 dark:border-emerald-400/20', dot: 'bg-emerald-500', pulse: false }
    case 'human_approved_with_changes':
      return { label: 'Approved ✎',   color: 'text-teal-600 dark:text-teal-400 bg-teal-50 dark:bg-teal-400/10 border-teal-200 dark:border-teal-400/20',                  dot: 'bg-teal-500',    pulse: false }
    default:
      return { label: status,         color: 'text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-400/10 border-slate-300 dark:border-slate-400/20',            dot: 'bg-slate-400',   pulse: false }
  }
}

export function severityMeta(sev?: string) {
  switch (sev) {
    case 'critical': return { label: 'Critical', color: 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-400/10 border-red-200 dark:border-red-400/30' }
    case 'high':     return { label: 'High',     color: 'text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-400/10 border-orange-200 dark:border-orange-400/30' }
    case 'medium':   return { label: 'Medium',   color: 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-400/10 border-amber-200 dark:border-amber-400/30' }
    case 'low':      return { label: 'Low',      color: 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-400/10 border-blue-200 dark:border-blue-400/30' }
    default:         return { label: 'Info',     color: 'text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-400/10 border-slate-200 dark:border-slate-400/30' }
  }
}

export function scoreColor(score: number): string {
  if (score >= 80) return '#22c55e'
  if (score >= 60) return '#f59e0b'
  if (score >= 40) return '#f97316'
  return '#ef4444'
}

export function scoreGrade(score: number): string {
  if (score >= 90) return 'A+'
  if (score >= 80) return 'A'
  if (score >= 70) return 'B'
  if (score >= 60) return 'C'
  if (score >= 50) return 'D'
  return 'F'
}

export function detectLang(filename: string): string {
  if (/Dockerfile/i.test(filename)) return 'dockerfile'
  if (/\.ya?ml$/i.test(filename))   return 'yaml'
  if (/\.tf(vars)?$/i.test(filename)) return 'hcl'
  if (/\.sh$/i.test(filename))      return 'bash'
  if (/\.json$/i.test(filename))    return 'json'
  if (/\.py$/i.test(filename))      return 'python'
  if (/\.ts(x)?$/i.test(filename))  return 'typescript'
  if (/\.js(x)?$/i.test(filename))  return 'javascript'
  if (/\.md$/i.test(filename))      return 'markdown'
  if (/\.toml$/i.test(filename))    return 'toml'
  if (/\.nginx|nginx\.conf/i.test(filename)) return 'nginx'
  return 'text'
}

export function isTerminalStatus(status: TaskStatus): boolean {
  return ['completed', 'failed', 'human_approved', 'human_approved_with_changes'].includes(status)
}
