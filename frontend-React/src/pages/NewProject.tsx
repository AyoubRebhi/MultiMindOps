import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { useCreateProject } from '@/hooks/useProjects'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { cn } from '@/lib/utils'
import type {
  ArchitectureType,
  ProjectCreatePayload,
  StrategyTier,
} from '@/types/project'

const ARCHITECTURE_OPTIONS: ArchitectureType[] = [
  'monolith',
  'microservices',
  'serverless',
  'static_site',
  'data_pipeline',
  'other',
]
const STRATEGY_OPTIONS: StrategyTier[] = ['minimal', 'balanced', 'robust']

export default function NewProject() {
  const navigate = useNavigate()
  const { mutateAsync, isPending, error } = useCreateProject()

  const [form, setForm] = useState<ProjectCreatePayload>({
    name: '',
    description: '',
    repository_url: '',
    architecture_type: 'monolith',
    application_profile: '',
    default_strategy_tier: 'balanced',
  })

  const update = <K extends keyof ProjectCreatePayload>(key: K, value: ProjectCreatePayload[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.name.trim()) return
    const payload: ProjectCreatePayload = {
      ...form,
      description: form.description?.trim() || undefined,
      repository_url: form.repository_url?.trim() || undefined,
      application_profile: form.application_profile?.trim() || undefined,
    }
    const created = await mutateAsync(payload)
    navigate(`/projects/${created.id}`)
  }

  return (
    <div className="p-6 max-w-2xl mx-auto animate-slide-in">
      <button
        type="button"
        onClick={() => navigate('/projects')}
        className="flex items-center gap-2 text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 mb-4"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> Projects
      </button>

      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">New Project</h1>
      <p className="text-sm text-slate-500 mt-1 mb-6">
        Define the target. Workflows you run later will attach to this project as persistent execution
        instances.
      </p>

      {error && (
        <div className="mb-4">
          <ErrorAlert message={error.message} />
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5">
        <Field label="Name" required>
          <input
            value={form.name}
            onChange={(e) => update('name', e.target.value)}
            placeholder="e.g. payments-api"
            className={inputClass}
            required
          />
        </Field>

        <Field label="Description">
          <textarea
            value={form.description ?? ''}
            onChange={(e) => update('description', e.target.value)}
            rows={3}
            placeholder="What does this project do, and why?"
            className={inputClass}
          />
        </Field>

        <Field label="Repository URL">
          <input
            value={form.repository_url ?? ''}
            onChange={(e) => update('repository_url', e.target.value)}
            placeholder="https://github.com/org/repo"
            className={inputClass}
          />
        </Field>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Architecture type">
            <select
              value={form.architecture_type ?? 'monolith'}
              onChange={(e) => update('architecture_type', e.target.value as ArchitectureType)}
              className={inputClass}
            >
              {ARCHITECTURE_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Default strategy tier">
            <select
              value={form.default_strategy_tier ?? 'balanced'}
              onChange={(e) => update('default_strategy_tier', e.target.value as StrategyTier)}
              className={inputClass}
            >
              {STRATEGY_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Field label="Application profile">
          <input
            value={form.application_profile ?? ''}
            onChange={(e) => update('application_profile', e.target.value)}
            placeholder="e.g. python-fastapi, node-express, jvm-spring"
            className={inputClass}
          />
        </Field>

        <div className="pt-2 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => navigate('/projects')}
            className="px-4 py-2 rounded-lg text-sm font-medium text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-white/[0.06] hover:bg-slate-50 dark:hover:bg-white/[0.04]"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isPending || !form.name.trim()}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-brand-600 hover:bg-brand-500 disabled:opacity-50 disabled:cursor-not-allowed text-white"
          >
            {isPending ? 'Creating…' : 'Create project'}
          </button>
        </div>
      </form>
    </div>
  )
}

const inputClass = cn(
  'w-full px-3 py-2 rounded-lg text-sm',
  'bg-white dark:bg-surface-800/40',
  'border border-slate-200 dark:border-white/[0.08]',
  'text-slate-900 dark:text-white',
  'placeholder:text-slate-400 dark:placeholder:text-slate-600',
  'focus:outline-none focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500/40',
)

function Field({
  label,
  required,
  children,
}: {
  label: string
  required?: boolean
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5 inline-block">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </span>
      {children}
    </label>
  )
}
