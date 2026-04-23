import { useState, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Sparkles,
  Globe,
  Lock,
  GitBranch,
  ChevronRight,
  RotateCcw,
  Upload,
  X,
  FileText,
  AlertCircle,
  ClipboardList,
} from 'lucide-react'
import { usePlanPreview, useGenerateArtifacts, useValidatePlan } from '@/hooks/useTasks'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { useTaskStore } from '@/store/taskStore'
import { PlanPreview } from '@/components/workflow/PlanPreview'
import { PlanViewer } from '@/components/workflow/PlanViewer'
import { ValidationPanel } from '@/components/workflow/ValidationPanel'
import { LogViewer } from '@/components/workflow/LogViewer'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { cn } from '@/lib/utils'
import type { PlanPreviewRequest, PlanPreviewResponse, PlanValidationDecision } from '@/types'

// ─── Step indicator ────────────────────────────────────────────────────────────
const STEPS = [
  { key: 'form',            label: 'Configure' },
  { key: 'plan',            label: 'Plan Review' },
  { key: 'plan_validation', label: 'Validation' },
  { key: 'generating',      label: 'Generating' },
  { key: 'result',          label: 'Done' },
]

function StepBar({ current }: { current: string }) {
  const idx = STEPS.findIndex((s) => s.key === current)
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {STEPS.map((step, i) => (
        <div key={step.key} className="flex items-center gap-1">
          <div
            className={cn(
              'flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-colors',
              i === idx
                ? 'bg-brand-50 dark:bg-brand-600/20 text-brand-700 dark:text-brand-300 border border-brand-200 dark:border-brand-500/30'
                : i < idx
                ? 'text-emerald-600 dark:text-emerald-400'
                : 'text-slate-400 dark:text-slate-600'
            )}
          >
            <span
              className={cn(
                'w-3.5 h-3.5 rounded-full border flex items-center justify-center text-[10px]',
                i < idx
                  ? 'border-emerald-400 dark:border-emerald-500/50 bg-emerald-50 dark:bg-emerald-500/20 text-emerald-600 dark:text-emerald-300'
                  : i === idx
                  ? 'border-brand-400 dark:border-brand-500/50 bg-brand-50 dark:bg-brand-600/20 text-brand-600 dark:text-brand-300'
                  : 'border-slate-300 dark:border-slate-700 text-slate-400 dark:text-slate-600'
              )}
            >
              {i < idx ? '✓' : i + 1}
            </span>
            {step.label}
          </div>
          {i < STEPS.length - 1 && (
            <ChevronRight className="w-3.5 h-3.5 text-slate-300 dark:text-slate-700" />
          )}
        </div>
      ))}
    </div>
  )
}

// ─── .env file dropzone ────────────────────────────────────────────────────────
interface EnvUploadProps {
  file: File | null
  onChange: (f: File | null) => void
  hasError?: boolean
}

function EnvFileUpload({ file, onChange, hasError }: EnvUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const dropped = e.dataTransfer.files[0]
    if (dropped) onChange(dropped)
  }

  return (
    <div>
      <label className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
        Environment file
        <span className="text-red-500">*</span>
        <span className="text-xs text-slate-400 dark:text-slate-500 font-normal ml-1">
          (.env, .env.example, etc.)
        </span>
      </label>

      {file ? (
        /* File selected pill */
        <div className={cn(
          'flex items-center gap-3 px-4 py-3 rounded-xl',
          'bg-emerald-50 dark:bg-emerald-500/10',
          'border border-emerald-200 dark:border-emerald-500/20'
        )}>
          <FileText className="w-4 h-4 text-emerald-500 dark:text-emerald-400 shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm text-emerald-700 dark:text-emerald-300 font-medium truncate">
              {file.name}
            </p>
            <p className="text-xs text-emerald-500/70 dark:text-emerald-400/60">
              {(file.size / 1024).toFixed(1)} KB
            </p>
          </div>
          <button
            type="button"
            onClick={() => onChange(null)}
            className="p-1 rounded text-emerald-500 hover:text-red-500 transition-colors"
            title="Remove file"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ) : (
        /* Drop zone */
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className={cn(
            'flex flex-col items-center justify-center gap-2 px-6 py-8 rounded-xl border-2 border-dashed cursor-pointer transition-colors',
            dragging
              ? 'border-brand-400 dark:border-brand-500/60 bg-brand-50 dark:bg-brand-600/10'
              : hasError
              ? 'border-red-300 dark:border-red-500/40 bg-red-50 dark:bg-red-500/5 hover:border-red-400 dark:hover:border-red-500/60'
              : cn(
                  'border-slate-200 dark:border-white/[0.08]',
                  'hover:border-slate-300 dark:hover:border-white/20',
                  'hover:bg-slate-50 dark:hover:bg-white/[0.02]'
                )
          )}
        >
          <Upload
            className={cn(
              'w-6 h-6',
              hasError
                ? 'text-red-400 dark:text-red-400'
                : 'text-slate-400 dark:text-slate-500'
            )}
          />
          <div className="text-center">
            <p className={cn(
              'text-sm font-medium',
              hasError
                ? 'text-red-500 dark:text-red-400'
                : 'text-slate-600 dark:text-slate-400'
            )}>
              {dragging ? 'Drop your .env file here' : 'Drop your .env file or click to browse'}
            </p>
            <p className="text-xs text-slate-400 dark:text-slate-600 mt-0.5">
              Used for security scanning — secrets are never stored
            </p>
          </div>
        </div>
      )}

      <input
        ref={inputRef}
        type="file"
        accept=".env,.env.*,text/plain"
        className="hidden"
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />

      {hasError && !file && (
        <p className="flex items-center gap-1.5 text-xs text-red-500 dark:text-red-400 mt-1.5">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          Please upload your .env file to continue.
        </p>
      )}
    </div>
  )
}

// ─── Validation ───────────────────────────────────────────────────────────────
interface FormValues {
  prompt: string
  repo_url: string
  repository_visibility: 'public' | 'private'
  github_token: string
}

interface FormErrors {
  prompt?: string
  repo_url?: string
  env_file?: string
  github_token?: string
}

function validate(values: FormValues, envFile: File | null): FormErrors {
  const errors: FormErrors = {}
  if (!values.prompt.trim())
    errors.prompt = 'Please describe what you want to automate.'
  if (!values.repo_url.trim())
    errors.repo_url = 'Repository URL is required.'
  else {
    try { new URL(values.repo_url) }
    catch { errors.repo_url = 'Enter a valid URL (e.g. https://github.com/owner/repo).' }
  }
  if (!envFile)
    errors.env_file = 'Please upload your .env file.'
  if (values.repository_visibility === 'private' && !values.github_token.trim())
    errors.github_token = 'GitHub token is required for private repositories.'
  return errors
}

// ─── Shared field helpers ─────────────────────────────────────────────────────
const fieldBase = cn(
  'w-full rounded-xl text-sm focus:outline-none transition-colors',
  'bg-white dark:bg-surface-800/50',
  'text-slate-800 dark:text-slate-200',
  'placeholder-slate-400 dark:placeholder-slate-600'
)

function FieldError({ msg }: { msg: string }) {
  return (
    <p className="flex items-center gap-1.5 text-xs text-red-500 dark:text-red-400 mt-1.5">
      <AlertCircle className="w-3.5 h-3.5 shrink-0" />
      {msg}
    </p>
  )
}

// ─── Step 1: Form ─────────────────────────────────────────────────────────────
function TaskForm({
  onSubmit,
  isLoading,
}: {
  onSubmit: (v: FormValues, envFile: File) => void
  isLoading: boolean
}) {
  const [form, setForm] = useState<FormValues>({
    prompt: '',
    repo_url: '',
    repository_visibility: 'public',
    github_token: '',
  })
  const [envFile, setEnvFile] = useState<File | null>(null)
  const [errors, setErrors]   = useState<FormErrors>({})
  const [touched, setTouched] = useState(false)

  const set = (k: keyof FormValues, v: string) => {
    const next = { ...form, [k]: v }
    setForm(next)
    if (touched) setErrors(validate(next, envFile))
  }

  const handleEnvChange = (f: File | null) => {
    setEnvFile(f)
    if (touched) setErrors(validate(form, f))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setTouched(true)
    const errs = validate(form, envFile)
    setErrors(errs)
    if (Object.keys(errs).length > 0) return
    onSubmit(form, envFile!)
  }

  const isPrivate = form.repository_visibility === 'private'

  const borderOk  = 'border border-slate-200 dark:border-white/[0.08] focus:border-brand-400 dark:focus:border-brand-500/40'
  const borderErr = 'border border-red-300 dark:border-red-500/40 focus:border-red-400 dark:focus:border-red-500/60'

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-6 animate-slide-in">

      {/* ── Task description ──────────────────────────────── */}
      <div>
        <label className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
          What do you want to automate?
          <span className="text-red-500">*</span>
        </label>
        <textarea
          value={form.prompt}
          onChange={(e) => set('prompt', e.target.value)}
          placeholder="e.g. Containerize my Node.js API with Docker, add Kubernetes manifests, set up a GitHub Actions CI/CD pipeline with SAST scanning…"
          rows={5}
          className={cn(fieldBase, 'px-4 py-3 resize-none', errors.prompt ? borderErr : borderOk)}
        />
        {errors.prompt && <FieldError msg={errors.prompt} />}
      </div>

      {/* ── Repository URL ────────────────────────────────── */}
      <div>
        <label className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
          Repository URL
          <span className="text-red-500">*</span>
        </label>
        <div className="relative">
          <GitBranch className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 dark:text-slate-500 pointer-events-none" />
          <input
            type="url"
            value={form.repo_url}
            onChange={(e) => set('repo_url', e.target.value)}
            placeholder="https://github.com/owner/repo"
            className={cn(fieldBase, 'pl-10 pr-4 py-2.5', errors.repo_url ? borderErr : borderOk)}
          />
        </div>
        {errors.repo_url
          ? <FieldError msg={errors.repo_url} />
          : <p className="text-xs text-slate-400 dark:text-slate-600 mt-1.5">Required for codebase analysis and security scanning.</p>}
      </div>

      {/* ── Visibility ────────────────────────────────────── */}
      <div>
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
          Repository visibility
        </label>
        <div className="flex gap-2">
          {(['public', 'private'] as const).map((vis) => (
            <button
              key={vis}
              type="button"
              onClick={() => set('repository_visibility', vis)}
              className={cn(
                'flex items-center gap-2 flex-1 px-4 py-2.5 rounded-xl border text-sm font-medium transition-colors',
                form.repository_visibility === vis
                  ? 'bg-brand-50 dark:bg-brand-600/20 border-brand-200 dark:border-brand-500/30 text-brand-700 dark:text-brand-300'
                  : cn(
                      'bg-white dark:bg-surface-800/40',
                      'border-slate-200 dark:border-white/[0.06]',
                      'text-slate-500 dark:text-slate-400',
                      'hover:border-slate-300 dark:hover:border-white/10',
                      'hover:text-slate-700 dark:hover:text-slate-300'
                    )
              )}
            >
              {vis === 'public' ? <Globe className="w-4 h-4" /> : <Lock className="w-4 h-4" />}
              {vis.charAt(0).toUpperCase() + vis.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* ── GitHub Token (private only) ───────────────────── */}
      {isPrivate && (
        <div className="animate-slide-in">
          <label className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
            <Lock className="w-3.5 h-3.5 text-amber-500 dark:text-amber-400" />
            GitHub Personal Access Token
            <span className="text-red-500">*</span>
          </label>
          <input
            type="password"
            value={form.github_token}
            onChange={(e) => set('github_token', e.target.value)}
            placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
            className={cn(
              fieldBase,
              'px-4 py-2.5 font-mono',
              errors.github_token ? borderErr : borderOk
            )}
          />
          {errors.github_token
            ? <FieldError msg={errors.github_token} />
            : (
              <p className="text-xs text-slate-400 dark:text-slate-600 mt-1.5">
                Needs <span className="font-mono text-slate-500 dark:text-slate-500">repo</span> scope.
                Token is only used for cloning and is never stored.
              </p>
            )}
        </div>
      )}

      {/* ── .env file upload ──────────────────────────────── */}
      <EnvFileUpload
        file={envFile}
        onChange={handleEnvChange}
        hasError={touched && !!errors.env_file}
      />

      {/* ── Submit ────────────────────────────────────────── */}
      <div className="pt-2 border-t border-slate-100 dark:border-white/[0.06]">
        <button
          type="submit"
          disabled={isLoading}
          className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isLoading ? (
            <>
              <LoadingSpinner className="w-4 h-4" />
              Analyzing…
            </>
          ) : (
            <>
              <Sparkles className="w-4 h-4" />
              Preview Plan
            </>
          )}
        </button>
      </div>
    </form>
  )
}

// ─── Step 3: Generating (polling UI) ─────────────────────────────────────────
function GeneratingView({ taskId }: { taskId: string }) {
  const navigate = useNavigate()

  useTaskPolling(taskId, {
    onComplete: (task) => navigate(`/tasks/${task.id}`, { replace: true }),
  })

  const stages = [
    { label: 'Codebase analysis',         color: 'bg-purple-500' },
    { label: 'Infrastructure generation', color: 'bg-blue-500' },
    { label: 'CI/CD pipeline build',      color: 'bg-brand-500' },
    { label: 'Security scanning',         color: 'bg-emerald-500' },
  ]

  return (
    <div className="space-y-5 animate-slide-in">
      <div className={cn(
        'flex items-center gap-4 p-4 rounded-xl',
        'bg-brand-50 dark:bg-brand-600/10',
        'border border-brand-200 dark:border-brand-500/20'
      )}>
        <LoadingSpinner className="w-5 h-5" />
        <div>
          <p className="text-sm font-medium text-brand-700 dark:text-brand-300">
            AI agents are working…
          </p>
          <p className="text-xs text-brand-600/60 dark:text-brand-400/60 mt-0.5">
            Generating infrastructure, CI/CD pipelines and running security scans. 30–90 seconds.
          </p>
        </div>
      </div>

      <div className="space-y-3">
        {stages.map(({ label, color }) => (
          <div key={label}>
            <div className="flex items-center justify-between text-xs text-slate-400 dark:text-slate-500 mb-1">
              <span>{label}</span>
              <LoadingSpinner className="w-3 h-3" />
            </div>
            <div className="h-1 rounded-full bg-slate-200 dark:bg-surface-700">
              <div
                className={`h-1 rounded-full ${color} opacity-70 animate-pulse`}
                style={{ width: '60%' }}
              />
            </div>
          </div>
        ))}
      </div>

      <p className="text-xs text-slate-400 dark:text-slate-600 text-center">
        Task ID: <span className="font-mono">{taskId}</span> ·{' '}
        <button
          onClick={() => navigate(`/tasks/${taskId}`)}
          className="text-brand-600 dark:text-brand-500 hover:text-brand-500 dark:hover:text-brand-400 underline underline-offset-2"
        >
          open full view
        </button>
      </p>
    </div>
  )
}

// ─── Human validation view ────────────────────────────────────────────────────
function PlanValidationView({
  preview,
  onDecision,
  onBack,
  isLoading,
  rejectedMessage,
}: {
  preview: PlanPreviewResponse
  onDecision: (decision: PlanValidationDecision, feedback?: string) => Promise<void>
  onBack: () => void
  isLoading: boolean
  rejectedMessage?: string | null
}) {
  const plan = preview.plan
  const logs = preview.logs

  return (
    <div className="space-y-6 animate-slide-in">
      {/* Header banner */}
      <div className={cn(
        'flex items-start gap-3 px-4 py-3 rounded-xl',
        'bg-brand-50 dark:bg-brand-600/10',
        'border border-brand-200 dark:border-brand-500/20'
      )}>
        <ClipboardList className="w-5 h-5 text-brand-500 dark:text-brand-400 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-brand-700 dark:text-brand-300">
            Human validation required
          </p>
          <p className="text-xs text-brand-600/70 dark:text-brand-400/60 mt-0.5">
            Review the generated plan below and choose an action. Execution is blocked until you decide.
          </p>
        </div>
      </div>

      {/* Logs */}
      {logs?.length > 0 && (
        <div>
          <p className="text-xs font-medium text-slate-400 dark:text-slate-500 mb-2">
            Plan generation logs
          </p>
          <LogViewer logs={logs} className="h-28" autoScroll={false} />
        </div>
      )}

      {/* Plan details */}
      {plan && <PlanViewer plan={plan} />}

      {/* Decision panel */}
      <ValidationPanel
        onDecision={onDecision}
        isLoading={isLoading}
        rejectedMessage={rejectedMessage}
      />

      {/* Back link */}
      {!rejectedMessage && (
        <button
          onClick={onBack}
          disabled={isLoading}
          className="text-xs text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300 transition-colors disabled:opacity-40"
        >
          ← Go back and edit request
        </button>
      )}
    </div>
  )
}

// ─── Main page ─────────────────────────────────────────────────────────────────
export default function NewTask() {
  const { wizard, setWizard, resetWizard } = useTaskStore()
  const planPreview   = usePlanPreview()
  const generate      = useGenerateArtifacts()
  const validatePlan  = useValidatePlan()
  const [error, setError]                   = useState<string | null>(null)
  const [rejectedMsg, setRejectedMsg]       = useState<string | null>(null)
  const [cachedEnvFile, setCachedEnvFile]   = useState<File | undefined>()

  const handleFormSubmit = async (values: FormValues, envFile: File) => {
    setError(null)
    setRejectedMsg(null)
    setCachedEnvFile(envFile)
    const req: PlanPreviewRequest = {
      prompt:                values.prompt,
      repo_url:              values.repo_url,
      repository_visibility: values.repository_visibility,
      github_token:          values.github_token || undefined,
    }
    try {
      const preview = await planPreview.mutateAsync({ payload: req, envFile })
      const nextStep = preview.requires_user_input ? 'plan_validation' : 'plan'
      setWizard({ step: nextStep, planPreview: preview, formData: req })
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // Standard plan-approval path (artifact selection)
  const handleApprove = useCallback(
    async (approvedArtifacts: string[]) => {
      if (!wizard.formData) return
      setError(null)
      try {
        const task = await generate.mutateAsync({
          payload: { ...wizard.formData, approved_artifacts: approvedArtifacts },
          envFile: cachedEnvFile,
        })
        setWizard({ step: 'generating', task })
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [wizard.formData, generate, setWizard, cachedEnvFile]
  )

  // Human validation decision (approve / reject / modify)
  const handleValidationDecision = useCallback(
    async (decision: PlanValidationDecision, feedback?: string) => {
      const taskId = wizard.planPreview?.task_id
      if (!taskId) {
        setError('No task ID found in plan preview response. Cannot validate.')
        return
      }
      setError(null)
      try {
        const result = await validatePlan.mutateAsync({ task_id: taskId, decision, feedback })

        if (decision === 'reject') {
          setRejectedMsg(result.message ?? 'The plan has been rejected. You can start a new task.')
          return
        }

        if (decision === 'approve') {
          // Backend continues execution — navigate to the generating/polling view
          // Use the task_id from the validate-plan response
          setWizard({ step: 'generating', task: { id: result.task_id } as Parameters<typeof setWizard>[0]['task'] })
          return
        }

        if (decision === 'modify') {
          // Reload the updated plan returned by the backend
          if (result.plan) {
            const updatedPreview = {
              ...wizard.planPreview!,
              plan: result.plan,
              task_id: result.task_id,
              requires_user_input: result.requires_user_input ?? true,
            }
            const nextStep = result.requires_user_input ? 'plan_validation' : 'plan'
            setWizard({ step: nextStep, planPreview: updatedPreview })
          }
        }
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [wizard.planPreview, validatePlan, setWizard]
  )

  const step = wizard.step

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">New Task</h1>
          <p className="text-sm text-slate-500 mt-1">
            Describe your goal, link your repo, and upload your .env — the AI handles the rest.
          </p>
        </div>
        {step !== 'form' && (
          <button
            onClick={() => {
              resetWizard()
              setError(null)
              setRejectedMsg(null)
              setCachedEnvFile(undefined)
            }}
            className="flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500 hover:text-slate-700 dark:hover:text-white transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Start over
          </button>
        )}
      </div>

      {/* Step bar */}
      <StepBar current={step} />

      {/* Error */}
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {/* Card */}
      <div className={cn(
        'rounded-2xl p-6',
        'bg-white dark:bg-surface-800/30',
        'border border-slate-200 dark:border-white/[0.06]'
      )}>
        {step === 'form' && (
          <TaskForm onSubmit={handleFormSubmit} isLoading={planPreview.isPending} />
        )}

        {/* Standard plan-review (artifact selection) */}
        {step === 'plan' && wizard.planPreview && (
          <>
            {wizard.planPreview.logs?.length > 0 && (
              <div className="mb-6">
                <p className="text-xs font-medium text-slate-400 dark:text-slate-500 mb-2">
                  Plan preview logs
                </p>
                <LogViewer logs={wizard.planPreview.logs} className="h-32" autoScroll={false} />
              </div>
            )}
            <PlanPreview
              preview={wizard.planPreview}
              originalPrompt={wizard.formData?.prompt ?? ''}
              onApprove={handleApprove}
              onBack={() => setWizard({ step: 'form' })}
              isLoading={generate.isPending}
            />
          </>
        )}

        {/* Human validation step */}
        {step === 'plan_validation' && wizard.planPreview && (
          <PlanValidationView
            preview={wizard.planPreview}
            onDecision={handleValidationDecision}
            onBack={() => setWizard({ step: 'form' })}
            isLoading={validatePlan.isPending}
            rejectedMessage={rejectedMsg}
          />
        )}

        {step === 'generating' && wizard.task && (
          <GeneratingView taskId={wizard.task.id} />
        )}
      </div>
    </div>
  )
}
