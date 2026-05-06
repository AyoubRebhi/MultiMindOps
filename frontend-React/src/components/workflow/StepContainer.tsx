import { ChevronLeft, ChevronRight, CheckCircle2, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useWorkflowStore, STEP_META } from '@/store/workflowStore'

// ── Action button ─────────────────────────────────────────────────────────────

interface ActionButtonProps {
  onClick: () => void
  disabled?: boolean
  loading?: boolean
  variant?: 'primary' | 'secondary' | 'ghost'
  icon?: React.ReactNode
  children: React.ReactNode
}

function ActionButton({
  onClick,
  disabled,
  loading,
  variant = 'secondary',
  icon,
  children,
}: ActionButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      className={cn(
        'flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-colors',
        'disabled:opacity-40 disabled:cursor-not-allowed',
        variant === 'primary' && cn(
          'bg-brand-600 hover:bg-brand-500 text-white',
          'shadow-sm shadow-brand-500/20',
        ),
        variant === 'secondary' && cn(
          'bg-white dark:bg-surface-800/50 text-slate-700 dark:text-slate-300',
          'border border-slate-200 dark:border-white/[0.08]',
          'hover:bg-slate-50 dark:hover:bg-white/[0.05]',
          'hover:border-slate-300 dark:hover:border-white/[0.12]',
        ),
        variant === 'ghost' && cn(
          'text-slate-500 dark:text-slate-400',
          'hover:text-slate-700 dark:hover:text-slate-200',
          'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
        ),
      )}
    >
      {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : icon}
      {children}
    </button>
  )
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  children: React.ReactNode

  // Bottom bar actions
  onBack?: () => void
  onApprove?: () => void
  onNext?: () => void

  approveLabel?: string
  approveIcon?: React.ReactNode

  isLoading?: boolean
  approveDisabled?: boolean
  hideActions?: boolean

  // Optional extra content in the action bar (e.g. edit controls)
  actionExtras?: React.ReactNode
}

// ── Main ──────────────────────────────────────────────────────────────────────

export function StepContainer({
  children,
  onBack,
  onApprove,
  onNext,
  approveLabel = 'Approve & Continue',
  approveIcon,
  isLoading,
  approveDisabled,
  hideActions,
  actionExtras,
}: Props) {
  const { currentStep } = useWorkflowStore()
  const meta = STEP_META[currentStep]

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* ── Step header ── */}
      <div className={cn(
        'shrink-0 px-6 py-4 border-b',
        'bg-white dark:bg-surface-900',
        'border-slate-200 dark:border-white/[0.06]',
      )}>
        <div className="flex items-center gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white leading-tight">
              {meta.label}
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
              {meta.description}
            </p>
          </div>
        </div>
      </div>

      {/* ── Scrollable content ── */}
      <div className="flex-1 overflow-y-auto">
        <div className="px-6 py-5">
          {children}
        </div>
      </div>

      {/* ── Bottom action bar ── */}
      {!hideActions && (
        <div className={cn(
          'shrink-0 flex items-center justify-between gap-3 px-6 py-3',
          'border-t border-slate-200 dark:border-white/[0.06]',
          'bg-white dark:bg-surface-900',
        )}>
          {/* Left: Back */}
          <div className="flex items-center gap-2">
            {onBack && (
              <ActionButton
                onClick={onBack}
                disabled={isLoading}
                variant="ghost"
                icon={<ChevronLeft className="w-4 h-4" />}
              >
                Back
              </ActionButton>
            )}
            {actionExtras}
          </div>

          {/* Right: Approve / Next */}
          <div className="flex items-center gap-2">
            {onNext && (
              <ActionButton
                onClick={onNext}
                disabled={isLoading}
                variant="secondary"
                icon={<ChevronRight className="w-4 h-4" />}
              >
                Next
              </ActionButton>
            )}
            {onApprove && (
              <ActionButton
                onClick={onApprove}
                loading={isLoading || approveDisabled}
                disabled={approveDisabled}
                variant="primary"
                icon={approveIcon ?? <CheckCircle2 className="w-4 h-4" />}
              >
                {approveLabel}
              </ActionButton>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
