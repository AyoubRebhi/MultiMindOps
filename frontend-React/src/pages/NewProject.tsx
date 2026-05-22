import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Github, Globe, Lock, Sparkles } from 'lucide-react'
import { useCreateProject } from '@/hooks/useProjects'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { cn } from '@/lib/utils'
import type { ProjectCreatePayload, RepositoryVisibility } from '@/types/project'

// The new minimal create flow asks for the smallest possible set of inputs:
// name + repository URL + visibility. Everything else (architecture, stack,
// service topology) is inferred by the AI bootstrap that fires as soon as
// the backend returns 201. The OPTIONAL GitHub credentials section is UI-
// only for now — wired into the credential vault in a later phase.

export default function NewProject() {
  const navigate = useNavigate()
  const { mutateAsync, isPending, error } = useCreateProject()

  const [name, setName] = useState('')
  const [repoUrl, setRepoUrl] = useState('')
  const [visibility, setVisibility] = useState<RepositoryVisibility>('public')
  const [showCreds, setShowCreds] = useState(false)
  const [ghUser, setGhUser] = useState('')
  const [ghToken, setGhToken] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    const payload: ProjectCreatePayload = {
      name: name.trim(),
      repository_url: repoUrl.trim() || undefined,
      repository_visibility: visibility,
    }
    const created = await mutateAsync(payload)
    // ProjectDetail polls the bootstrap state, so the user sees the
    // "Analyzing repository…" skeleton as soon as they land there.
    navigate(`/projects/${created.id}`)
  }

  const canSubmit = name.trim().length > 0 && !isPending

  return (
    <div className="p-6 max-w-2xl mx-auto animate-slide-in">
      <button
        type="button"
        onClick={() => navigate('/projects')}
        className="flex items-center gap-2 text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 mb-4"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> Projects
      </button>

      <div className="flex items-center gap-3 mb-2">
        <div className="p-2 rounded-xl bg-brand-500/10 text-brand-600 dark:text-brand-400">
          <Sparkles className="w-5 h-5" />
        </div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          New Project
        </h1>
      </div>
      <p className="text-sm text-slate-500 mt-1 mb-6">
        Point us at a repository. We'll analyze the codebase, detect the architecture,
        and propose deployment strategies automatically.
      </p>

      {error && (
        <div className="mb-4">
          <ErrorAlert message={error.message} />
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5" aria-busy={isPending}>
        <Field label="Project name" required>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. payments-api"
            className={inputClass}
            autoFocus
            required
            disabled={isPending}
          />
        </Field>

        <Field label="Repository URL">
          <input
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/org/repo"
            className={inputClass}
            disabled={isPending}
          />
          <p className="text-[11px] text-slate-500 mt-1">
            Leave blank to set up later. With a URL, the AI bootstrap will run as
            soon as the project is created.
          </p>
        </Field>

        <Field label="Repository visibility">
          <div className="grid grid-cols-2 gap-2">
            <VisibilityOption
              active={visibility === 'public'}
              icon={<Globe className="w-4 h-4" />}
              label="Public"
              hint="Accessible without authentication"
              onClick={() => setVisibility('public')}
              disabled={isPending}
            />
            <VisibilityOption
              active={visibility === 'private'}
              icon={<Lock className="w-4 h-4" />}
              label="Private"
              hint="Requires GitHub credentials"
              onClick={() => setVisibility('private')}
              disabled={isPending}
            />
          </div>
        </Field>

        {/* Optional GitHub credentials section — UI placeholder. Not posted
            to the backend yet; the credential vault wiring lands in a later
            phase. Kept inside the form for parity with how the field group
            will eventually persist. */}
        {visibility === 'private' && (
          <details
            open={showCreds}
            onToggle={(e) => setShowCreds((e.currentTarget as HTMLDetailsElement).open)}
            className={cn(
              'rounded-xl p-4',
              'bg-slate-50 dark:bg-surface-800/40',
              'border border-slate-200 dark:border-white/[0.06]',
            )}
          >
            <summary className="flex items-center gap-2 cursor-pointer text-sm font-medium text-slate-700 dark:text-slate-300">
              <Github className="w-4 h-4" /> GitHub credentials
              <span className="text-[11px] font-normal text-slate-500 ml-1">
                (optional, not stored yet)
              </span>
            </summary>
            <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="GitHub username">
                <input
                  value={ghUser}
                  onChange={(e) => setGhUser(e.target.value)}
                  placeholder="octocat"
                  className={inputClass}
                  disabled={isPending}
                />
              </Field>
              <Field label="Personal access token">
                <input
                  value={ghToken}
                  onChange={(e) => setGhToken(e.target.value)}
                  type="password"
                  placeholder="ghp_…"
                  className={inputClass}
                  disabled={isPending}
                />
              </Field>
            </div>
            <p className="text-[11px] text-slate-500 mt-3">
              Credential vault integration is coming in a follow-up. Tokens entered
              here are kept in the browser only and will not be sent yet.
            </p>
          </details>
        )}

        {isPending && <BootstrapProgress />}

        <div className="pt-2 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => navigate('/projects')}
            disabled={isPending}
            className="px-4 py-2 rounded-lg text-sm font-medium text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-white/[0.06] hover:bg-slate-50 dark:hover:bg-white/[0.04] disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-brand-600 hover:bg-brand-500 disabled:opacity-50 disabled:cursor-not-allowed text-white inline-flex items-center gap-2"
          >
            {isPending ? (
              <>
                <span className="w-3 h-3 rounded-full border-2 border-white/60 border-t-transparent animate-spin" />
                Creating…
              </>
            ) : (
              <>
                <Sparkles className="w-3.5 h-3.5" /> Create &amp; analyze
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  )
}

// ─── Helpers ────────────────────────────────────────────────────────────────

const inputClass = cn(
  'w-full px-3 py-2 rounded-lg text-sm',
  'bg-white dark:bg-surface-800/40',
  'border border-slate-200 dark:border-white/[0.08]',
  'text-slate-900 dark:text-white',
  'placeholder:text-slate-400 dark:placeholder:text-slate-600',
  'focus:outline-none focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500/40',
  'disabled:opacity-60',
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

function VisibilityOption({
  active,
  icon,
  label,
  hint,
  onClick,
  disabled,
}: {
  active: boolean
  icon: React.ReactNode
  label: string
  hint: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'p-3 rounded-lg text-left transition-colors border',
        'flex items-start gap-3',
        active
          ? 'border-brand-500/60 bg-brand-50 dark:bg-brand-600/10'
          : 'border-slate-200 dark:border-white/[0.08] hover:border-slate-300 dark:hover:border-white/[0.16]',
        'disabled:opacity-60',
      )}
    >
      <span
        className={cn(
          'mt-0.5 inline-flex items-center justify-center w-6 h-6 rounded-md',
          active
            ? 'bg-brand-500/15 text-brand-700 dark:text-brand-300'
            : 'bg-slate-100 dark:bg-white/[0.05] text-slate-500',
        )}
      >
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-medium text-slate-900 dark:text-white">
          {label}
        </span>
        <span className="block text-[11px] text-slate-500 mt-0.5">{hint}</span>
      </span>
    </button>
  )
}

// Progress strip rendered while the create request is in flight. Once the
// backend returns 201 the user is navigated to ProjectDetail, which renders
// its own (more detailed) bootstrap state based on bootstrap_status.
function BootstrapProgress() {
  return (
    <div
      className={cn(
        'rounded-xl p-4',
        'bg-brand-50/40 dark:bg-brand-600/5',
        'border border-brand-200/60 dark:border-brand-500/20',
      )}
    >
      <div className="flex items-center gap-2 text-sm font-medium text-brand-700 dark:text-brand-300 mb-3">
        <Sparkles className="w-4 h-4" />
        Bootstrapping your project…
      </div>
      <ul className="space-y-2 text-xs text-slate-600 dark:text-slate-400">
        <ProgressLine label="Creating project record" pulse />
        <ProgressLine label="Scheduling repository analysis" pulse />
        <ProgressLine label="Detecting architecture" />
        <ProgressLine label="Building project context" />
      </ul>
    </div>
  )
}

function ProgressLine({ label, pulse }: { label: string; pulse?: boolean }) {
  return (
    <li className="flex items-center gap-2">
      <span
        className={cn(
          'w-1.5 h-1.5 rounded-full',
          pulse
            ? 'bg-brand-500 animate-pulse'
            : 'bg-slate-300 dark:bg-white/[0.08]',
        )}
      />
      {label}
    </li>
  )
}
