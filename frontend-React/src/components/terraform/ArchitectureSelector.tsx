import { Server, Boxes, Cloud, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import type { TerraformArchitecture } from '@/api/terraform'

interface ArchOption {
  value: TerraformArchitecture
  label: string
  description: string
  icon: React.ElementType
}

const ARCH_OPTIONS: ArchOption[] = [
  {
    value: 'monolith',
    label: 'Monolith',
    description: 'Single ECS service · RDS Multi-AZ · ALB',
    icon: Server,
  },
  {
    value: 'microservices',
    label: 'Microservices',
    description: 'EKS cluster · RDS Multi-AZ · ALB',
    icon: Boxes,
  },
  {
    value: 'serverless',
    label: 'Serverless',
    description: 'Lambda + API Gateway · fully managed',
    icon: Cloud,
  },
]

export interface ArchitectureSelectorValue {
  architecture: TerraformArchitecture
  projectName: string
}

interface Props {
  value: ArchitectureSelectorValue
  onChange: (next: ArchitectureSelectorValue) => void
  onSubmit: () => void
  isSubmitting?: boolean
  submitLabel?: string
  className?: string
}

export function ArchitectureSelector({
  value,
  onChange,
  onSubmit,
  isSubmitting,
  submitLabel = 'Generate Terraform',
  className,
}: Props) {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!isSubmitting) onSubmit()
  }

  return (
    <form onSubmit={handleSubmit} className={cn('space-y-6', className)}>
      <div>
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
          Architecture
          <span className="text-red-500 ml-1">*</span>
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {ARCH_OPTIONS.map(({ value: v, label, description, icon: Icon }) => {
            const active = value.architecture === v
            return (
              <button
                key={v}
                type="button"
                onClick={() => onChange({ ...value, architecture: v })}
                className={cn(
                  'flex flex-col items-start gap-2 px-4 py-3 rounded-xl border text-left transition-colors',
                  active
                    ? 'bg-orange-50 dark:bg-orange-500/10 border-orange-200 dark:border-orange-500/30 text-orange-700 dark:text-orange-300'
                    : cn(
                        'bg-white dark:bg-surface-800/40',
                        'border-slate-200 dark:border-white/[0.06]',
                        'text-slate-700 dark:text-slate-300',
                        'hover:border-slate-300 dark:hover:border-white/10',
                      ),
                )}
              >
                <div className="flex items-center gap-2">
                  <Icon className={cn('w-4 h-4', active ? 'text-orange-500 dark:text-orange-400' : 'text-slate-400 dark:text-slate-500')} />
                  <span className="text-sm font-medium">{label}</span>
                </div>
                <span className={cn(
                  'text-xs',
                  active
                    ? 'text-orange-700/80 dark:text-orange-300/70'
                    : 'text-slate-500 dark:text-slate-500',
                )}>
                  {description}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
            Tier
          </label>
          <div className={cn(
            'flex items-center justify-between px-4 py-2.5 rounded-xl text-sm',
            'bg-slate-50 dark:bg-surface-800/40',
            'border border-slate-200 dark:border-white/[0.06]',
            'text-slate-600 dark:text-slate-400',
          )}>
            <span className="font-medium">balanced</span>
            <span className="text-xs text-slate-400 dark:text-slate-500">only tier available</span>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
            Project name
            <span className="text-xs text-slate-400 dark:text-slate-500 font-normal ml-1">(optional)</span>
          </label>
          <input
            type="text"
            value={value.projectName}
            onChange={(e) => onChange({ ...value, projectName: e.target.value })}
            placeholder="my-app"
            maxLength={32}
            className={cn(
              'w-full px-4 py-2.5 rounded-xl text-sm focus:outline-none transition-colors',
              'bg-white dark:bg-surface-800/50',
              'border border-slate-200 dark:border-white/[0.08]',
              'focus:border-brand-400 dark:focus:border-brand-500/40',
              'text-slate-800 dark:text-slate-200',
              'placeholder-slate-400 dark:placeholder-slate-600',
            )}
          />
        </div>
      </div>

      <div className="pt-2">
        <button
          type="submit"
          disabled={isSubmitting}
          className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isSubmitting ? (
            <>
              <LoadingSpinner className="w-4 h-4" />
              Generating…
            </>
          ) : (
            <>
              <Sparkles className="w-4 h-4" />
              {submitLabel}
            </>
          )}
        </button>
      </div>
    </form>
  )
}
