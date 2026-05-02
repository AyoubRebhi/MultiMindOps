import { useState } from 'react'
import { Download, Box, Cloud, Server, Workflow, FileCode } from 'lucide-react'
import { CodeViewer } from './CodeViewer'
import { cn } from '@/lib/utils'

// ── Artifact key → display filename + language ────────────────────────────────
const DISPLAY_NAME: Record<string, string> = {
  dockerfile:             'Dockerfile',
  dockerignore:           '.dockerignore',
  docker_compose:         'docker-compose.yml',
  env_example:            '.env.example',
  terraform_providers:    'providers.tf',
  terraform_backend:      'backend.tf',
  terraform_vpc:          'vpc.tf',
  terraform_compute:      'compute.tf',
  terraform_eks:          'eks.tf',
  terraform_variables:    'variables.tf',
  terraform_outputs:      'outputs.tf',
  terraform_main:         'main.tf',
  terraform_iam:          'iam.tf',
  terraform_sg:           'security_groups.tf',
  terraform_alb:          'alb.tf',
  kubernetes_deployment:  'deployment.yaml',
  kubernetes_service:     'service.yaml',
  kubernetes_ingress:     'ingress.yaml',
  kubernetes_configmap:   'configmap.yaml',
  kubernetes_hpa:         'hpa.yaml',
  kubernetes_namespace:   'namespace.yaml',
  github_actions_workflow: 'ci-cd.yml',
  cicd_workflow:          'ci-cd.yml',
}

function displayName(key: string): string {
  return DISPLAY_NAME[key] ?? key
}

function artifactLang(key: string): string {
  if (key === 'dockerfile')                          return 'dockerfile'
  if (key === 'dockerignore')                        return 'bash'
  if (key.startsWith('docker_'))                     return 'yaml'
  if (key.startsWith('terraform_'))                  return 'hcl'
  if (key.startsWith('kubernetes_'))                 return 'yaml'
  if (key.includes('workflow') || key === 'cicd')    return 'yaml'
  return 'text'
}

// ── Domain classification ─────────────────────────────────────────────────────
type Domain = 'docker' | 'terraform' | 'kubernetes' | 'cicd' | 'other'

const DOMAIN_CONFIG: Record<Domain, { label: string; icon: React.ElementType; color: string }> = {
  docker:     { label: 'Docker',      icon: Box,      color: 'text-cyan-600 dark:text-cyan-400' },
  terraform:  { label: 'Terraform',   icon: Cloud,    color: 'text-orange-600 dark:text-orange-400' },
  kubernetes: { label: 'Kubernetes',  icon: Server,   color: 'text-blue-600 dark:text-blue-400' },
  cicd:       { label: 'CI/CD',       icon: Workflow, color: 'text-purple-600 dark:text-purple-400' },
  other:      { label: 'Other',       icon: FileCode, color: 'text-slate-600 dark:text-slate-400' },
}

function classifyKey(key: string): Domain {
  if (['dockerfile', 'dockerignore', 'docker_compose', 'env_example'].includes(key)) return 'docker'
  if (key.startsWith('docker_')) return 'docker'
  if (key.startsWith('terraform_')) return 'terraform'
  if (key.startsWith('kubernetes_')) return 'kubernetes'
  if (key.includes('workflow') || key.includes('cicd') || key.includes('github_actions')) return 'cicd'
  return 'other'
}

// Kubernetes contract reference pattern
const TF_OUTPUT_RE = /\$\{terraform_output:[^}]+\}/

function downloadFile(name: string, content: string) {
  const blob = new Blob([content], { type: 'text/plain' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

interface Props {
  artifacts: Record<string, string>
  cicdArtifacts?: Record<string, string>
}

export function ArtifactTabs({ artifacts, cicdArtifacts }: Props) {
  // Merge CI/CD artifacts in
  const merged: Record<string, string> = { ...artifacts, ...cicdArtifacts }
  const allKeys = Object.keys(merged)

  if (!allKeys.length) return null

  // Group by domain
  const grouped: Partial<Record<Domain, string[]>> = {}
  for (const key of allKeys) {
    const domain = classifyKey(key)
    if (!grouped[domain]) grouped[domain] = []
    grouped[domain]!.push(key)
  }

  const domainOrder: Domain[] = ['docker', 'terraform', 'kubernetes', 'cicd', 'other']
  const activeDomains = domainOrder.filter(d => grouped[d]?.length)

  const [activeDomain, setActiveDomain] = useState<Domain>(activeDomains[0] ?? 'other')
  const [activeFile, setActiveFile] = useState<string>(() => grouped[activeDomains[0] ?? 'other']?.[0] ?? '')

  const domainFiles = grouped[activeDomain] ?? []
  const activeCode  = merged[activeFile] ?? ''
  const isKubernetes = activeDomain === 'kubernetes'

  function selectDomain(d: Domain) {
    setActiveDomain(d)
    setActiveFile(grouped[d]?.[0] ?? '')
  }

  return (
    <div className={cn(
      'rounded-xl overflow-hidden',
      'bg-white dark:bg-surface-900',
      'border border-slate-200 dark:border-white/[0.06]',
    )}>
      {/* Domain tab bar */}
      <div className={cn(
        'flex items-center gap-1 overflow-x-auto px-3 py-2',
        'bg-slate-50 dark:bg-surface-800/40',
        'border-b border-slate-200 dark:border-white/[0.06]',
      )}>
        {activeDomains.map(domain => {
          const { label, icon: Icon, color } = DOMAIN_CONFIG[domain]
          const isActive = activeDomain === domain
          return (
            <button
              key={domain}
              onClick={() => selectDomain(domain)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors border',
                isActive
                  ? cn('border-slate-200 dark:border-white/[0.08]', color,
                       'bg-white dark:bg-surface-900 shadow-sm')
                  : cn('border-transparent text-slate-500 dark:text-slate-500',
                       'hover:text-slate-700 dark:hover:text-slate-300',
                       'hover:bg-slate-100 dark:hover:bg-white/[0.04]')
              )}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
              <span className={cn(
                'px-1.5 py-0.5 rounded text-[10px]',
                isActive
                  ? 'bg-slate-100 dark:bg-white/[0.08] text-slate-500'
                  : 'bg-slate-100 dark:bg-white/[0.04] text-slate-400 dark:text-slate-600'
              )}>
                {grouped[domain]!.length}
              </span>
            </button>
          )
        })}

        <div className="ml-auto shrink-0">
          <button
            onClick={() => activeFile && downloadFile(displayName(activeFile), merged[activeFile])}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs border border-transparent transition-colors',
              'text-slate-500 dark:text-slate-500',
              'hover:text-slate-900 dark:hover:text-white',
              'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
              'hover:border-slate-200 dark:hover:border-white/[0.06]',
            )}
          >
            <Download className="w-3.5 h-3.5" />
            Download
          </button>
        </div>
      </div>

      <div className="flex">
        {/* File list sidebar (only when domain has multiple files) */}
        {domainFiles.length > 1 && (
          <div className={cn(
            'w-44 shrink-0 py-2',
            'border-r border-slate-200 dark:border-white/[0.06]',
            'bg-slate-50 dark:bg-surface-800/20',
          )}>
            {domainFiles.map(key => (
              <button
                key={key}
                onClick={() => setActiveFile(key)}
                className={cn(
                  'w-full text-left px-3 py-1.5 text-xs font-mono transition-colors',
                  activeFile === key
                    ? 'text-brand-700 dark:text-brand-300 bg-brand-50 dark:bg-brand-500/10'
                    : 'text-slate-500 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/[0.04]'
                )}
              >
                {displayName(key)}
              </button>
            ))}
          </div>
        )}

        {/* Code viewer */}
        <div className="flex-1 min-w-0">
          {isKubernetes && TF_OUTPUT_RE.test(activeCode) && (
            <div className={cn(
              'flex items-center gap-2 px-4 py-2 text-xs',
              'bg-orange-50 dark:bg-orange-500/10',
              'border-b border-orange-200 dark:border-orange-500/20',
              'text-orange-700 dark:text-orange-300',
            )}>
              <span className="font-semibold">Terraform contract references detected</span>
              <span className="text-orange-500 dark:text-orange-400">
                — highlighted values are injected from Terraform outputs at deploy time.
              </span>
            </div>
          )}
          {activeFile ? (
            <CodeViewer
              code={activeCode}
              language={artifactLang(activeFile)}
              filename={displayName(activeFile)}
              showLineNumbers
            />
          ) : (
            <div className="flex items-center justify-center h-32 text-sm text-slate-400 dark:text-slate-600">
              Select a file
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
