import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Layers, RotateCcw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ArchitectureSelector, type ArchitectureSelectorValue } from '@/components/terraform/ArchitectureSelector'
import { ArtifactViewer } from '@/components/terraform/ArtifactViewer'
import { ValidationPanel } from '@/components/terraform/ValidationPanel'
import {
  terraformApi,
  type TerraformArchitecture,
  type TerraformArtifact,
  type TerraformValidationResult,
} from '@/api/terraform'

const DEFAULT_FORM: ArchitectureSelectorValue = {
  architecture: 'monolith',
  projectName: '',
}

export default function TerraformPage() {
  const { artifactId } = useParams<{ artifactId?: string }>()
  const navigate = useNavigate()

  const [form, setForm] = useState<ArchitectureSelectorValue>(DEFAULT_FORM)
  const [artifact, setArtifact] = useState<TerraformArtifact | null>(null)
  const [validation, setValidation] = useState<TerraformValidationResult | null>(null)

  const [isGenerating, setIsGenerating] = useState(false)
  const [isLoadingArtifact, setIsLoadingArtifact] = useState(false)
  const [isValidating, setIsValidating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reload artifact when a deep-link id is present (or changes).
  useEffect(() => {
    if (!artifactId) {
      setArtifact(null)
      setValidation(null)
      return
    }
    if (artifact?.id === artifactId) return

    let cancelled = false
    setIsLoadingArtifact(true)
    setError(null)
    terraformApi
      .get(artifactId)
      .then((data) => {
        if (cancelled) return
        setArtifact(data)
        setValidation(null)
        const meta = data.metadata as Record<string, unknown>
        const arch = (meta?.architecture as TerraformArchitecture) ?? form.architecture
        setForm((prev) => ({ ...prev, architecture: arch }))
      })
      .catch((e: Error) => {
        if (cancelled) return
        setError(e.message)
      })
      .finally(() => {
        if (!cancelled) setIsLoadingArtifact(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifactId])

  const handleGenerate = useCallback(async () => {
    setError(null)
    setIsGenerating(true)
    try {
      const data = await terraformApi.generate({
        architecture: form.architecture,
        tier: 'balanced',
        project_name: form.projectName.trim() || undefined,
      })
      setArtifact(data)
      setValidation(null)
      navigate(`/terraform/${data.id}`, { replace: false })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setIsGenerating(false)
    }
  }, [form, navigate])

  const handleValidate = useCallback(async () => {
    if (!artifact) return
    setError(null)
    setIsValidating(true)
    try {
      const result = await terraformApi.validate(artifact.id)
      setValidation(result)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setIsValidating(false)
    }
  }, [artifact])

  const handleReset = useCallback(() => {
    setArtifact(null)
    setValidation(null)
    setError(null)
    setForm(DEFAULT_FORM)
    navigate('/terraform', { replace: false })
  }, [navigate])

  const meta = artifact?.metadata as Record<string, unknown> | undefined
  const archLabel  = (meta?.architecture as string) ?? form.architecture
  const tierLabel  = (meta?.tier as string) ?? 'balanced'
  const regionLabel = (meta?.aws_region as string) ?? undefined

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6 animate-slide-in">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-lg bg-orange-50 dark:bg-orange-500/10 border border-orange-200 dark:border-orange-500/20">
            <Layers className="w-5 h-5 text-orange-600 dark:text-orange-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
              Terraform Generation
            </h1>
            <p className="text-sm text-slate-500 mt-1">
              Pick an architecture, generate Terraform, and validate it locally.
            </p>
          </div>
        </div>
        {(artifact || artifactId) && (
          <button
            onClick={handleReset}
            className="flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500 hover:text-slate-700 dark:hover:text-white transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Start over
          </button>
        )}
      </div>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {/* Form card */}
      <div className={cn(
        'rounded-2xl p-6',
        'bg-white dark:bg-surface-800/30',
        'border border-slate-200 dark:border-white/[0.06]',
      )}>
        <ArchitectureSelector
          value={form}
          onChange={setForm}
          onSubmit={handleGenerate}
          isSubmitting={isGenerating}
        />
      </div>

      {/* Loading state for deep-link reload */}
      {isLoadingArtifact && !artifact && (
        <div className="flex items-center justify-center gap-3 py-12">
          <LoadingSpinner className="w-5 h-5" />
          <span className="text-sm text-slate-500 dark:text-slate-400">Loading artifact…</span>
        </div>
      )}

      {/* Artifact + validation */}
      {artifact && (
        <>
          <div className={cn(
            'flex flex-wrap items-center gap-2 px-4 py-3 rounded-xl',
            'bg-orange-50 dark:bg-orange-500/10',
            'border border-orange-200 dark:border-orange-500/20',
          )}>
            <span className="text-xs font-semibold text-orange-700 dark:text-orange-300 uppercase tracking-wider">
              Artifact
            </span>
            <span className="text-xs font-mono text-orange-700/80 dark:text-orange-300/80">
              {artifact.id}
            </span>
            <span className="text-xs text-orange-600/70 dark:text-orange-400/60">·</span>
            <span className="text-xs text-orange-700 dark:text-orange-300">{archLabel}</span>
            <span className="text-xs text-orange-600/70 dark:text-orange-400/60">·</span>
            <span className="text-xs text-orange-700 dark:text-orange-300">{tierLabel}</span>
            {regionLabel && (
              <>
                <span className="text-xs text-orange-600/70 dark:text-orange-400/60">·</span>
                <span className="text-xs text-orange-700 dark:text-orange-300">{regionLabel}</span>
              </>
            )}
            <span className="ml-auto text-xs text-orange-600/70 dark:text-orange-400/60">
              {Object.keys(artifact.files).length} file{Object.keys(artifact.files).length === 1 ? '' : 's'}
            </span>
          </div>

          <ArtifactViewer
            files={artifact.files}
            title="Generated Terraform"
            subtitle="Review the files before validating."
          />

          <div className={cn(
            'rounded-2xl p-5',
            'bg-white dark:bg-surface-800/30',
            'border border-slate-200 dark:border-white/[0.06]',
          )}>
            <ValidationPanel
              result={validation}
              isValidating={isValidating}
              onValidate={handleValidate}
            />
          </div>
        </>
      )}
    </div>
  )
}
