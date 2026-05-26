import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import * as ToastPrimitive from '@radix-ui/react-toast'
import { AlertTriangle, CheckCircle, Info, X, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

export type ToastVariant = 'info' | 'success' | 'warning' | 'error'

interface ToastOptions {
  title: string
  description?: string
  variant?: ToastVariant
  durationMs?: number
}

interface ToastItem extends Required<Omit<ToastOptions, 'description'>> {
  id: number
  description?: string
}

interface ToastContextValue {
  show: (opts: ToastOptions) => number
  dismiss: (id: number) => void
  success: (title: string, description?: string) => number
  error: (title: string, description?: string) => number
  warning: (title: string, description?: string) => number
  info: (title: string, description?: string) => number
}

const ToastContext = createContext<ToastContextValue | null>(null)

const VARIANT_CFG: Record<
  ToastVariant,
  { icon: React.ElementType; iconClass: string; ringClass: string }
> = {
  info:    { icon: Info,           iconClass: 'text-brand-500 dark:text-brand-400',         ringClass: 'ring-brand-500/20' },
  success: { icon: CheckCircle,    iconClass: 'text-emerald-500 dark:text-emerald-400',     ringClass: 'ring-emerald-500/20' },
  warning: { icon: AlertTriangle,  iconClass: 'text-amber-500 dark:text-amber-400',         ringClass: 'ring-amber-500/20' },
  error:   { icon: XCircle,        iconClass: 'text-red-500 dark:text-red-400',             ringClass: 'ring-red-500/20' },
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const counter = useRef(0)

  const dismiss = useCallback((id: number) => {
    setItems((curr) => curr.filter((t) => t.id !== id))
  }, [])

  const show = useCallback((opts: ToastOptions): number => {
    const id = ++counter.current
    setItems((curr) => [
      ...curr,
      {
        id,
        title: opts.title,
        description: opts.description,
        variant: opts.variant ?? 'info',
        durationMs: opts.durationMs ?? 5000,
      },
    ])
    return id
  }, [])

  const value = useMemo<ToastContextValue>(
    () => ({
      show,
      dismiss,
      success: (t, d) => show({ title: t, description: d, variant: 'success' }),
      error:   (t, d) => show({ title: t, description: d, variant: 'error', durationMs: 8000 }),
      warning: (t, d) => show({ title: t, description: d, variant: 'warning' }),
      info:    (t, d) => show({ title: t, description: d, variant: 'info' }),
    }),
    [show, dismiss],
  )

  return (
    <ToastContext.Provider value={value}>
      <ToastPrimitive.Provider swipeDirection="right" duration={5000}>
        {children}
        {items.map((t) => {
          const cfg = VARIANT_CFG[t.variant]
          const Icon = cfg.icon
          return (
            <ToastPrimitive.Root
              key={t.id}
              duration={t.durationMs}
              onOpenChange={(open) => { if (!open) dismiss(t.id) }}
              className={cn(
                'group relative pointer-events-auto flex items-start gap-3 p-4 rounded-lg overflow-hidden',
                'bg-white dark:bg-surface-900',
                'border border-slate-200 dark:border-white/[0.08]',
                'shadow-lg ring-1', cfg.ringClass,
                'data-[state=open]:animate-slide-in',
                'data-[state=closed]:opacity-0 data-[state=closed]:transition-opacity',
              )}
            >
              <Icon className={cn('w-5 h-5 mt-0.5 shrink-0', cfg.iconClass)} />
              <div className="flex-1 min-w-0">
                <ToastPrimitive.Title className="text-sm font-medium text-slate-900 dark:text-white">
                  {t.title}
                </ToastPrimitive.Title>
                {t.description && (
                  <ToastPrimitive.Description className="mt-0.5 text-xs text-slate-500 dark:text-slate-400 break-words">
                    {t.description}
                  </ToastPrimitive.Description>
                )}
              </div>
              <ToastPrimitive.Close
                aria-label="Dismiss"
                className="shrink-0 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
              >
                <X className="w-4 h-4" />
              </ToastPrimitive.Close>
            </ToastPrimitive.Root>
          )
        })}
        <ToastPrimitive.Viewport
          className={cn(
            'fixed top-4 right-4 z-[100] flex flex-col gap-2 w-[360px] max-w-[calc(100vw-2rem)]',
            'outline-none',
          )}
        />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}
