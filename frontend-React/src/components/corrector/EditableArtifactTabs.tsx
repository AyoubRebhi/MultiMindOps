import { useEffect, useMemo, useState } from 'react'
import { diffLines } from 'diff'
import { RotateCcw, Save, GitCompare, FileCode, CheckCircle, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  displayName,
  getArtifacts,
  patchArtifacts,
  resetArtifact,
  type ArtifactKey,
  type ArtifactMeta,
  type GetArtifactsResponse,
} from '@/services/workflowApi'

const KEYS: ArtifactKey[] = ['dockerfile', 'docker_compose', 'dockerignore']

function languageFor(key: ArtifactKey) {
  if (key === 'dockerfile' || key === 'dockerignore') return 'dockerfile'
  return 'yaml'
}

function Editor({
  value,
  onChange,
  options,
}: {
  height?: string
  language?: string
  value: string
  theme?: string
  onChange?: (value: string) => void
  options?: { readOnly?: boolean; [key: string]: unknown }
}) {
  return (
    <textarea
      value={value}
      readOnly={options?.readOnly}
      onChange={(event) => onChange?.(event.target.value)}
      spellCheck={false}
      className={cn(
        'h-[420px] w-full resize-none rounded-lg border border-slate-800 bg-[#080b12] p-4',
        'font-mono text-xs leading-relaxed text-slate-200 outline-none',
        'focus:border-amber-500/50 read-only:text-slate-400',
      )}
    />
  )
}

function DiffBlock({ before, after }: { before: string; after: string }) {
  return (
    <div className="bg-[#080b12] border border-slate-800 rounded-lg overflow-auto max-h-[420px] font-mono text-xs">
      {diffLines(before, after).map((part, index) => {
        const kind = part.added ? 'add' : part.removed ? 'remove' : 'context'
        return part.value.split('\n').filter(Boolean).map((line, lineIndex) => (
          <div
            key={`${index}-${lineIndex}`}
            className={cn(
              'flex min-w-0 leading-5',
              kind === 'add' && 'bg-emerald-500/10 text-emerald-300',
              kind === 'remove' && 'bg-red-500/10 text-red-300',
              kind === 'context' && 'text-slate-500',
            )}
          >
            <span className="w-8 shrink-0 text-center select-none border-r border-slate-800">
              {kind === 'add' ? '+' : kind === 'remove' ? '-' : ' '}
            </span>
            <span className="px-3 whitespace-pre">{line}</span>
          </div>
        ))
      })}
    </div>
  )
}

interface Props {
  taskId: string
  onDirtyChange?: (dirty: boolean) => void
  onArtifactsSaved?: () => void
  refreshToken?: number
}

export function EditableArtifactTabs({ taskId, onDirtyChange, onArtifactsSaved, refreshToken = 0 }: Props) {
  const [data, setData] = useState<GetArtifactsResponse>()
  const [drafts, setDrafts] = useState<Partial<Record<ArtifactKey, string>>>({})
  const [active, setActive] = useState<ArtifactKey>('dockerfile')
  const [view, setView] = useState<'current' | 'original' | 'ai' | 'diff'>('current')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string>()
  const [error, setError] = useState<string>()

  async function load() {
    setError(undefined)
    const next = await getArtifacts(taskId)
    setData(next)
    const loaded = Object.fromEntries(
      KEYS.map((key) => [key, next.metadata[key]?.current_content ?? next.artifacts[key] ?? '']),
    ) as Partial<Record<ArtifactKey, string>>
    setDrafts(loaded)
  }

  useEffect(() => {
    load().catch((e) => setError((e as Error).message))
  }, [taskId, refreshToken])

  const activeMeta: ArtifactMeta | undefined = data?.metadata?.[active]
  const current = drafts[active] ?? ''
  const original = activeMeta?.original_content ?? activeMeta?.generated_content ?? ''
  const aiPatch = activeMeta?.ai_patched_content ?? ''
  const compareBase = view === 'ai' && aiPatch ? aiPatch : original

  const dirty = useMemo(() => {
    return KEYS.some((key) => (drafts[key] ?? '') !== (data?.metadata?.[key]?.current_content ?? ''))
  }, [drafts, data])

  useEffect(() => {
    onDirtyChange?.(dirty)
  }, [dirty, onDirtyChange])

  async function handleSave() {
    setSaving(true)
    setMessage(undefined)
    setError(undefined)
    try {
      const changed = Object.fromEntries(
        KEYS
          .filter((key) => (drafts[key] ?? '') !== (data?.metadata?.[key]?.current_content ?? ''))
          .map((key) => [key, drafts[key] ?? '']),
      ) as Partial<Record<ArtifactKey, string>>
      if (!Object.keys(changed).length) {
        setMessage('No changes to save.')
        return
      }
      const result = await patchArtifacts(taskId, changed)
      setMessage(`Saved version ${result.versions[active] ?? Object.values(result.versions)[0]}.`)
      await load()
      onArtifactsSaved?.()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function handleReset() {
    setSaving(true)
    setMessage(undefined)
    setError(undefined)
    try {
      await resetArtifact(taskId, active)
      setMessage(`${displayName(active)} reset to original.`)
      await load()
      onArtifactsSaved?.()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-xl border border-slate-700/70 bg-[#0a0d14] overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-b border-slate-800">
        <FileCode className="w-4 h-4 text-slate-400" />
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">Editable Artifacts</p>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setView(view === 'diff' ? 'current' : 'diff')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-slate-700 text-xs text-slate-300 hover:bg-slate-800"
          >
            <GitCompare className="w-3.5 h-3.5" />
            Compare
          </button>
          <button
            onClick={handleReset}
            disabled={saving}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-slate-700 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Reset
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !dirty}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold',
              dirty ? 'bg-emerald-500 text-slate-950 hover:bg-emerald-400' : 'bg-slate-800 text-slate-500',
            )}
          >
            <Save className="w-3.5 h-3.5" />
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-b border-slate-800">
        {KEYS.map((key) => {
          const meta = data?.metadata?.[key]
          const isDirty = (drafts[key] ?? '') !== (meta?.current_content ?? '')
          return (
            <button
              key={key}
              onClick={() => setActive(key)}
              className={cn(
                'px-3 py-1.5 rounded-md text-xs font-mono border',
                active === key
                  ? 'border-amber-500/50 bg-amber-500/10 text-amber-200'
                  : 'border-slate-700 text-slate-400 hover:text-slate-200',
              )}
            >
              {displayName(key)}
              <span className="ml-2 text-[10px] text-slate-500">v{meta?.version ?? 1}</span>
              {isDirty && <span className="ml-1 text-amber-300">*</span>}
            </button>
          )
        })}
        <div className="ml-auto flex gap-1 rounded-md border border-slate-700 p-1">
          {(['current', 'original', 'ai'] as const).map((item) => (
            <button
              key={item}
              onClick={() => setView(item)}
              className={cn(
                'px-2.5 py-1 rounded text-[11px] capitalize',
                view === item ? 'bg-slate-700 text-slate-100' : 'text-slate-500 hover:text-slate-300',
              )}
            >
              {item === 'ai' ? 'AI patch' : item}
            </button>
          ))}
        </div>
      </div>

      <div className="px-4 py-3 flex flex-wrap items-center gap-3 text-xs text-slate-500 border-b border-slate-800">
        <span>Version {activeMeta?.version ?? 1}</span>
        <span>Last edited by {activeMeta?.last_modified_by ?? 'generator'}</span>
        {activeMeta?.updated_at && <span>{new Date(activeMeta.updated_at).toLocaleString()}</span>}
        {activeMeta?.user_modified && <span className="text-amber-300">User modified</span>}
      </div>

      {(message || error) && (
        <div className={cn('flex items-center gap-2 px-4 py-2 text-xs', error ? 'text-red-300' : 'text-emerald-300')}>
          {error ? <AlertCircle className="w-3.5 h-3.5" /> : <CheckCircle className="w-3.5 h-3.5" />}
          {error ?? message}
        </div>
      )}

      <div className="p-4">
        {view === 'diff' ? (
          <DiffBlock before={compareBase} after={current} />
        ) : view === 'original' ? (
          <Editor height="420px" language={languageFor(active)} value={original} theme="vs-dark" options={{ readOnly: true, minimap: { enabled: false }, wordWrap: 'on' }} />
        ) : view === 'ai' ? (
          <Editor height="420px" language={languageFor(active)} value={aiPatch || 'No AI patch proposal stored for this artifact.'} theme="vs-dark" options={{ readOnly: true, minimap: { enabled: false }, wordWrap: 'on' }} />
        ) : (
          <Editor
            height="420px"
            language={languageFor(active)}
            value={current}
            theme="vs-dark"
            onChange={(value) => setDrafts((prev) => ({ ...prev, [active]: value ?? '' }))}
            options={{ minimap: { enabled: false }, wordWrap: 'on', fontSize: 12, scrollBeyondLastLine: false }}
          />
        )}
      </div>
    </div>
  )
}
