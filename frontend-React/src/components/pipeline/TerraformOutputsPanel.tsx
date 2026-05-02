import { useState } from 'react'
import { ArrowRight, Copy, Check, Globe, Server, Container, Network } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { TerraformOutputs } from '@/types'

interface OutputCardDef {
  key: keyof TerraformOutputs
  label: string
  description: string
  icon: React.ElementType
  consumedBy: string
  iconColor: string
  borderColor: string
  bgColor: string
}

const OUTPUT_CARDS: OutputCardDef[] = [
  {
    key: 'cluster_endpoint',
    label: 'Cluster Endpoint',
    description: 'EKS API server URL',
    icon: Server,
    consumedBy: 'kubernetes/deployment.yaml',
    iconColor: 'text-blue-500',
    borderColor: 'border-blue-200 dark:border-blue-500/20',
    bgColor: 'bg-blue-50 dark:bg-blue-500/10',
  },
  {
    key: 'cluster_name',
    label: 'Cluster Name',
    description: 'EKS cluster identifier',
    icon: Server,
    consumedBy: 'kubernetes/configmap.yaml',
    iconColor: 'text-indigo-500',
    borderColor: 'border-indigo-200 dark:border-indigo-500/20',
    bgColor: 'bg-indigo-50 dark:bg-indigo-500/10',
  },
  {
    key: 'ecr_repository_url',
    label: 'ECR Repository URL',
    description: 'Container image registry',
    icon: Container,
    consumedBy: 'kubernetes/deployment.yaml (image field)',
    iconColor: 'text-orange-500',
    borderColor: 'border-orange-200 dark:border-orange-500/20',
    bgColor: 'bg-orange-50 dark:bg-orange-500/10',
  },
  {
    key: 'load_balancer_dns',
    label: 'Load Balancer DNS',
    description: 'ALB / NLB public endpoint',
    icon: Globe,
    consumedBy: 'kubernetes/ingress.yaml',
    iconColor: 'text-emerald-500',
    borderColor: 'border-emerald-200 dark:border-emerald-500/20',
    bgColor: 'bg-emerald-50 dark:bg-emerald-500/10',
  },
  {
    key: 'vpc_id',
    label: 'VPC ID',
    description: 'Virtual private cloud',
    icon: Network,
    consumedBy: 'kubernetes/service.yaml',
    iconColor: 'text-purple-500',
    borderColor: 'border-purple-200 dark:border-purple-500/20',
    bgColor: 'bg-purple-50 dark:bg-purple-500/10',
  },
]

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(value).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button
      onClick={handleCopy}
      className={cn(
        'p-1 rounded transition-colors',
        'text-slate-400 dark:text-slate-500',
        'hover:text-slate-700 dark:hover:text-slate-300',
        'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
      )}
      title="Copy value"
    >
      {copied ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
    </button>
  )
}

interface Props {
  outputs: TerraformOutputs
  className?: string
}

export function TerraformOutputsPanel({ outputs, className }: Props) {
  const knownCards = OUTPUT_CARDS.filter(c => outputs[c.key])

  // Collect any extra keys not covered by known cards
  const knownKeys = new Set(OUTPUT_CARDS.map(c => c.key as string))
  const extraEntries = Object.entries(outputs).filter(
    ([k, v]) => !knownKeys.has(k) && v
  )

  if (!knownCards.length && !extraEntries.length) return null

  return (
    <div className={cn(
      'rounded-xl overflow-hidden',
      'bg-white dark:bg-surface-900',
      'border border-slate-200 dark:border-white/[0.06]',
      className,
    )}>
      {/* Header with Terraform → Kubernetes contract banner */}
      <div className={cn(
        'px-4 py-3',
        'bg-gradient-to-r from-orange-50 to-blue-50 dark:from-orange-500/10 dark:to-blue-500/10',
        'border-b border-slate-200 dark:border-white/[0.06]',
      )}>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-semibold text-orange-700 dark:text-orange-300 uppercase tracking-wider">
            Terraform
          </span>
          <div className="flex items-center gap-1">
            <div className="h-0.5 w-6 bg-orange-300 dark:bg-orange-500/50 rounded" />
            <ArrowRight className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
            <div className="h-0.5 w-6 bg-blue-300 dark:bg-blue-500/50 rounded" />
          </div>
          <span className="text-xs font-semibold text-blue-700 dark:text-blue-300 uppercase tracking-wider">
            Kubernetes
          </span>
          <span className="ml-auto text-xs text-slate-400 dark:text-slate-500">
            Contract-based outputs
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          These values are injected into Kubernetes manifests via{' '}
          <code className="text-[10px] font-mono bg-slate-100 dark:bg-white/[0.06] px-1 py-0.5 rounded">
            {'${terraform_output:<key>}'}
          </code>{' '}
          references — no hardcoded AWS values.
        </p>
      </div>

      {/* Output cards grid */}
      <div className="p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {knownCards.map(card => {
          const value = outputs[card.key] as string
          const Icon = card.icon
          return (
            <div
              key={card.key}
              className={cn(
                'flex flex-col gap-2 p-3 rounded-lg border',
                card.borderColor,
                'bg-white dark:bg-surface-800/40',
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <div className={cn('p-1.5 rounded-md', card.bgColor)}>
                    <Icon className={cn('w-3.5 h-3.5', card.iconColor)} />
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-slate-700 dark:text-slate-200">
                      {card.label}
                    </p>
                    <p className="text-[10px] text-slate-400 dark:text-slate-500">
                      {card.description}
                    </p>
                  </div>
                </div>
                <CopyButton value={value} />
              </div>

              {/* Value */}
              <div className={cn(
                'text-[11px] font-mono px-2 py-1.5 rounded break-all leading-relaxed',
                'bg-slate-50 dark:bg-black/20',
                'text-slate-700 dark:text-slate-300',
                'border border-slate-100 dark:border-white/[0.04]',
              )}>
                {value}
              </div>

              {/* Consumed by */}
              <div className="flex items-center gap-1 text-[10px] text-slate-400 dark:text-slate-500">
                <ArrowRight className="w-2.5 h-2.5 shrink-0" />
                <span className="font-mono">{card.consumedBy}</span>
              </div>
            </div>
          )
        })}

        {/* Extra/unknown outputs */}
        {extraEntries.map(([key, value]) => (
          <div
            key={key}
            className={cn(
              'flex flex-col gap-2 p-3 rounded-lg border',
              'border-slate-200 dark:border-white/[0.06]',
              'bg-white dark:bg-surface-800/40',
            )}
          >
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold font-mono text-slate-600 dark:text-slate-300">
                {key}
              </p>
              <CopyButton value={value as string} />
            </div>
            <div className={cn(
              'text-[11px] font-mono px-2 py-1.5 rounded break-all',
              'bg-slate-50 dark:bg-black/20',
              'text-slate-600 dark:text-slate-400',
              'border border-slate-100 dark:border-white/[0.04]',
            )}>
              {value as string}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
