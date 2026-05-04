import { useRef, useState } from 'react'
import {
  Sparkles,
  Globe,
  Lock,
  GitBranch,
  Upload,
  X,
  FileText,
  AlertCircle,
} from 'lucide-react'
import { StepContainer } from '@/components/workflow/StepContainer'
import { useWorkflowStore } from '@/store/workflowStore'
import { cn } from '@/lib/utils'

// ── Helpers ───────────────────────────────────────────────────────────────────

const fieldBase = cn(
  'w-full rounded-xl text-sm focus:outline-none transition-colors',
  'bg-white dark:bg-surface-800/50',
  'text-slate-800 dark:text-slate-200',
  'placeholder-slate-400 dark:placeholder-slate-600',
)
const borderOk  = 'border border-slate-200 dark:border-white/[0.08] focus:border-brand-400 dark:focus:border-brand-500/40'
const borderErr = 'border border-red-300 dark:border-red-500/40 focus:border-red-400 dark:focus:border-red-500/60'

function FieldError({ msg }: { msg: string }) {
  return (
    <p className="flex items-center gap-1.5 text-xs text-red-500 dark:text-red-400 mt-1.5">
      <AlertCircle className="w-3.5 h-3.5 shrink-0" />
      {msg}
    </p>
  )
}

// ── .env upload ───────────────────────────────────────────────────────────────

function EnvFileUpload({
  file,
  onChange,
  hasError,
}: {
  file: File | null
  onChange: (f: File | null) => void
  hasError?: boolean
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) onChange(f)
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
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20">
          <FileText className="w-4 h-4 text-emerald-500 shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm text-emerald-700 dark:text-emerald-300 font-medium truncate">{file.name}</p>
            <p className="text-xs text-emerald-500/70">{(file.size / 1024).toFixed(1)} KB</p>
          </div>
          <button type="button" onClick={() => onChange(null)} className="p-1 rounded text-emerald-500 hover:text-red-500 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
      ) : (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={cn(
            'flex flex-col items-center justify-center gap-2 px-6 py-8 rounded-xl border-2 border-dashed cursor-pointer transition-colors',
            dragging
              ? 'border-brand-400 dark:border-brand-500/60 bg-brand-50 dark:bg-brand-600/10'
              : hasError
              ? 'border-red-300 dark:border-red-500/40 bg-red-50 dark:bg-red-500/5'
              : 'border-slate-200 dark:border-white/[0.08] hover:border-slate-300 dark:hover:border-white/20 hover:bg-slate-50 dark:hover:bg-white/[0.02]',
          )}
        >
          <Upload className={cn('w-6 h-6', hasError ? 'text-red-400' : 'text-slate-400 dark:text-slate-500')} />
          <div className="text-center">
            <p className={cn('text-sm font-medium', hasError ? 'text-red-500' : 'text-slate-600 dark:text-slate-400')}>
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
        <FieldError msg="Please upload your .env file to continue." />
      )}
    </div>
  )
}

// ── Validation ────────────────────────────────────────────────────────────────

interface FormErrors {
  prompt?: string
  repo_url?: string
  env_file?: string
  github_token?: string
}

function validateForm(
  values: { prompt: string; repo_url: string; repository_visibility: string; github_token: string },
  envFile: File | null,
): FormErrors {
  const e: FormErrors = {}
  if (!values.prompt.trim()) e.prompt = 'Please describe what you want to automate.'
  if (!values.repo_url.trim()) {
    e.repo_url = 'Repository URL is required.'
  } else {
    try { new URL(values.repo_url) } catch { e.repo_url = 'Enter a valid URL (e.g. https://github.com/owner/repo).' }
  }
  if (!envFile) e.env_file = 'Please upload your .env file.'
  if (values.repository_visibility === 'private' && !values.github_token.trim())
    e.github_token = 'GitHub token is required for private repositories.'
  return e
}

// ── Main ──────────────────────────────────────────────────────────────────────

interface Props {
  onSubmit: (envFile: File) => void
  isLoading: boolean
}

export function InputStep({ onSubmit, isLoading }: Props) {
  const { userInput, setUserInput, envFile, setEnvFile } = useWorkflowStore()
  const [localEnvFile, setLocalEnvFile] = useState<File | null>(envFile ?? null)
  const [errors, setErrors] = useState<FormErrors>({})
  const [touched, setTouched] = useState(false)

  const set = (k: keyof typeof userInput, v: string) => {
    setUserInput({ [k]: v })
    if (touched) setErrors(validateForm({ ...userInput, [k]: v }, localEnvFile))
  }

  const handleEnv = (f: File | null) => {
    setLocalEnvFile(f)
    setEnvFile(f ?? undefined)
    if (touched) setErrors(validateForm(userInput, f))
  }

  const handleSubmit = () => {
    setTouched(true)
    const errs = validateForm(userInput, localEnvFile)
    setErrors(errs)
    if (Object.keys(errs).length > 0) return
    onSubmit(localEnvFile!)
  }

  const isPrivate = userInput.repository_visibility === 'private'

  return (
    <StepContainer
      onApprove={handleSubmit}
      approveLabel="Preview Plan"
      approveIcon={<Sparkles className="w-4 h-4" />}
      isLoading={isLoading}
    >
      <div className="max-w-2xl space-y-6">

        {/* Prompt */}
        <div>
          <label className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
            What do you want to automate?
            <span className="text-red-500">*</span>
          </label>
          <textarea
            value={userInput.prompt}
            onChange={(e) => set('prompt', e.target.value)}
            placeholder="e.g. Containerize my Node.js API with Docker, add Kubernetes manifests, set up a GitHub Actions CI/CD pipeline with SAST scanning…"
            rows={5}
            className={cn(fieldBase, 'px-4 py-3 resize-none', errors.prompt ? borderErr : borderOk)}
          />
          {errors.prompt && <FieldError msg={errors.prompt} />}
        </div>

        {/* Repo URL */}
        <div>
          <label className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
            Repository URL
            <span className="text-red-500">*</span>
          </label>
          <div className="relative">
            <GitBranch className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 dark:text-slate-500 pointer-events-none" />
            <input
              type="url"
              value={userInput.repo_url}
              onChange={(e) => set('repo_url', e.target.value)}
              placeholder="https://github.com/owner/repo"
              className={cn(fieldBase, 'pl-10 pr-4 py-2.5', errors.repo_url ? borderErr : borderOk)}
            />
          </div>
          {errors.repo_url
            ? <FieldError msg={errors.repo_url} />
            : <p className="text-xs text-slate-400 dark:text-slate-600 mt-1.5">Required for codebase analysis and security scanning.</p>}
        </div>

        {/* Visibility */}
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
                  userInput.repository_visibility === vis
                    ? 'bg-brand-50 dark:bg-brand-600/20 border-brand-200 dark:border-brand-500/30 text-brand-700 dark:text-brand-300'
                    : 'bg-white dark:bg-surface-800/40 border-slate-200 dark:border-white/[0.06] text-slate-500 dark:text-slate-400 hover:border-slate-300 dark:hover:border-white/10',
                )}
              >
                {vis === 'public' ? <Globe className="w-4 h-4" /> : <Lock className="w-4 h-4" />}
                {vis.charAt(0).toUpperCase() + vis.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* GitHub Token */}
        {isPrivate && (
          <div className="animate-slide-in">
            <label className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              <Lock className="w-3.5 h-3.5 text-amber-500 dark:text-amber-400" />
              GitHub Personal Access Token
              <span className="text-red-500">*</span>
            </label>
            <input
              type="password"
              value={userInput.github_token}
              onChange={(e) => set('github_token', e.target.value)}
              placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
              className={cn(fieldBase, 'px-4 py-2.5 font-mono', errors.github_token ? borderErr : borderOk)}
            />
            {errors.github_token
              ? <FieldError msg={errors.github_token} />
              : <p className="text-xs text-slate-400 dark:text-slate-600 mt-1.5">
                  Needs <span className="font-mono text-slate-500">repo</span> scope. Never stored.
                </p>}
          </div>
        )}

        {/* .env upload */}
        <EnvFileUpload
          file={localEnvFile}
          onChange={handleEnv}
          hasError={touched && !!errors.env_file}
        />
      </div>
    </StepContainer>
  )
}
