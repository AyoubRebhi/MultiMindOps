import { useMemo, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Mail, Lock, User, Eye, EyeOff, ArrowRight, Check } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ErrorAlert } from '@/components/common/ErrorAlert'
import { cn } from '@/lib/utils'

interface LocationState {
  from?: { pathname?: string }
}

const EMAIL_RE = /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$/

interface PasswordChecks {
  length: boolean
  hasNumber: boolean
  hasMixed: boolean
}

function evaluatePassword(pw: string): PasswordChecks {
  return {
    length: pw.length >= 8,
    hasNumber: /\d/.test(pw),
    hasMixed: /[a-z]/.test(pw) && /[A-Z]/.test(pw),
  }
}

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [touched, setTouched] = useState<{ email?: boolean; password?: boolean }>({})

  const checks = useMemo(() => evaluatePassword(password), [password])
  const passwordOk = checks.length && checks.hasNumber && checks.hasMixed
  const emailOk = EMAIL_RE.test(email.trim())

  const emailInvalid = touched.email && !emailOk
  const passwordInvalid = touched.password && !passwordOk

  const canSubmit = emailOk && passwordOk && !submitting

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setTouched({ email: true, password: true })
    if (!canSubmit) return

    setError(null)
    setSubmitting(true)
    try {
      await register({
        email: email.trim().toLowerCase(),
        password,
        display_name: displayName.trim() || undefined,
      })
      const dest = (location.state as LocationState | null)?.from?.pathname ?? '/'
      navigate(dest, { replace: true })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Sign up failed'
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="w-full">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">
          Create your account
        </h1>
        <p className="mt-1.5 text-sm text-slate-500 dark:text-slate-400">
          Start automating your DevSecOps pipelines in minutes.
        </p>
      </header>

      {error && (
        <div className="mb-5">
          <ErrorAlert title="Sign up failed" message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      <form onSubmit={onSubmit} noValidate className="space-y-5">
        <Field label="Display name (optional)" icon={User}>
          <input
            type="text"
            autoComplete="name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Jane Doe"
            className={inputCls(false)}
            disabled={submitting}
            maxLength={120}
          />
        </Field>

        <Field
          label="Email"
          icon={Mail}
          error={emailInvalid ? 'Enter a valid email address' : undefined}
        >
          <input
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, email: true }))}
            placeholder="you@company.com"
            className={inputCls(!!emailInvalid)}
            disabled={submitting}
          />
        </Field>

        <Field
          label="Password"
          icon={Lock}
          trailing={
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              tabIndex={-1}
              className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          }
        >
          <input
            type={showPassword ? 'text' : 'password'}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, password: true }))}
            placeholder="Create a strong password"
            className={inputCls(!!passwordInvalid)}
            disabled={submitting}
          />
        </Field>

        <PasswordHints checks={checks} />

        <button
          type="submit"
          disabled={!canSubmit}
          className={cn(
            'w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors',
            'bg-brand-600 hover:bg-brand-500 text-white',
            'disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-brand-600',
          )}
        >
          {submitting ? (
            <>
              <LoadingSpinner className="w-4 h-4 text-white" />
              <span>Creating account…</span>
            </>
          ) : (
            <>
              <span>Create account</span>
              <ArrowRight className="w-4 h-4" />
            </>
          )}
        </button>
      </form>

      <p className="mt-6 text-center text-sm text-slate-500 dark:text-slate-400">
        Already have an account?{' '}
        <Link
          to="/login"
          state={location.state}
          className="font-medium text-brand-600 dark:text-brand-400 hover:underline"
        >
          Sign in
        </Link>
      </p>
    </div>
  )
}

function PasswordHints({ checks }: { checks: PasswordChecks }) {
  const items = [
    { ok: checks.length,    label: 'At least 8 characters' },
    { ok: checks.hasMixed,  label: 'Upper and lower case letters' },
    { ok: checks.hasNumber, label: 'At least one number' },
  ]
  return (
    <ul className="space-y-1.5">
      {items.map((it) => (
        <li
          key={it.label}
          className={cn(
            'flex items-center gap-2 text-xs',
            it.ok
              ? 'text-emerald-600 dark:text-emerald-400'
              : 'text-slate-500 dark:text-slate-500',
          )}
        >
          <Check
            className={cn(
              'w-3.5 h-3.5',
              it.ok ? 'opacity-100' : 'opacity-30',
            )}
          />
          <span>{it.label}</span>
        </li>
      ))}
    </ul>
  )
}

function Field({
  label,
  icon: Icon,
  error,
  trailing,
  children,
}: {
  label: string
  icon: React.ElementType
  error?: string
  trailing?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1.5">
        {label}
      </label>
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500">
          <Icon className="w-4 h-4" />
        </span>
        {children}
        {trailing && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2">{trailing}</span>
        )}
      </div>
      {error && <p className="mt-1 text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  )
}

function inputCls(error: boolean): string {
  return cn(
    'w-full pl-10 pr-10 py-2.5 rounded-lg text-sm transition-colors',
    'bg-white dark:bg-surface-900',
    'border',
    error
      ? 'border-red-300 dark:border-red-500/40 focus:border-red-400 dark:focus:border-red-400'
      : 'border-slate-200 dark:border-white/[0.08] focus:border-brand-500 dark:focus:border-brand-400',
    'text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-600',
    'focus:outline-none focus:ring-2 focus:ring-brand-500/20',
    'disabled:opacity-60 disabled:cursor-not-allowed',
  )
}
