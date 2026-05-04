/**
 * CodeEditor — view/edit toggle for generated artifacts.
 *
 * View mode:  react-syntax-highlighter (installed, zero-config)
 * Edit mode:  Monaco Editor if installed, else falls back to a styled textarea.
 *
 * To enable Monaco:  npm install @monaco-editor/react
 * Then uncomment the Monaco branch below (search "MONACO").
 */
import { lazy, Suspense, useState } from 'react'
import { Edit3, Eye, Copy, Check } from 'lucide-react'
import { CodeViewer } from '@/components/artifacts/CodeViewer'
import { cn } from '@/lib/utils'

// ── MONACO (optional) ─────────────────────────────────────────────────────────
// Uncomment once you run: npm install @monaco-editor/react
// import MonacoEditor from '@monaco-editor/react'
// import { useThemeStore } from '@/store/themeStore'

// ── Fallback textarea editor ──────────────────────────────────────────────────

function TextareaEditor({
  value,
  onChange,
  height,
}: {
  value: string
  onChange?: (v: string) => void
  height: string
}) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
      spellCheck={false}
      className={cn(
        'w-full font-mono text-xs resize-none outline-none p-4 leading-relaxed',
        'bg-[rgb(8,15,31)] text-slate-300',
        'placeholder-slate-600',
      )}
      style={{ height, minHeight: height }}
    />
  )
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  filename: string
  language?: string
  value: string
  onChange?: (value: string) => void
  readOnly?: boolean
  height?: string
}

// ── Main ──────────────────────────────────────────────────────────────────────

export function CodeEditor({
  filename,
  language = 'text',
  value,
  onChange,
  readOnly = false,
  height = '400px',
}: Props) {
  const [editing, setEditing] = useState(false)
  const [copied, setCopied]   = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(value).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className={cn(
      'rounded-xl overflow-hidden border',
      'border-slate-200 dark:border-white/[0.06]',
      'bg-white dark:bg-surface-900',
    )}>
      {/* ── Toolbar ── */}
      <div className={cn(
        'flex items-center justify-between gap-2 px-4 py-2 border-b',
        'bg-slate-50 dark:bg-surface-800/60',
        'border-slate-200 dark:border-white/[0.06]',
      )}>
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-xs text-slate-500 dark:text-slate-400 truncate">
            {filename}
          </span>
          <span className={cn(
            'shrink-0 px-1.5 py-0.5 rounded text-[10px] font-mono',
            'bg-slate-200 dark:bg-surface-700/60 text-slate-400 dark:text-slate-600',
          )}>
            {language}
          </span>
          {editing && (
            <span className={cn(
              'shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium',
              'bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400',
              'border border-amber-200 dark:border-amber-500/30',
            )}>
              <Edit3 className="w-2.5 h-2.5" />
              editing
            </span>
          )}
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={handleCopy}
            className={cn(
              'flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors',
              'text-slate-400 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-300',
              'hover:bg-slate-100 dark:hover:bg-white/[0.05]',
            )}
            title="Copy to clipboard"
          >
            {copied
              ? <Check className="w-3.5 h-3.5 text-emerald-500" />
              : <Copy  className="w-3.5 h-3.5" />}
          </button>

          {!readOnly && (
            <button
              onClick={() => setEditing((v) => !v)}
              className={cn(
                'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors border',
                editing
                  ? cn('bg-brand-50 dark:bg-brand-600/20 border-brand-200 dark:border-brand-500/30 text-brand-700 dark:text-brand-300')
                  : cn('border-slate-200 dark:border-white/[0.06] text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-white/[0.05]'),
              )}
            >
              {editing ? <Eye className="w-3 h-3" /> : <Edit3 className="w-3 h-3" />}
              {editing ? 'View' : 'Edit'}
            </button>
          )}
        </div>
      </div>

      {/* ── Content ── */}
      {editing ? (
        // ── MONACO: replace TextareaEditor with MonacoEditor once installed ──
        // <MonacoEditor
        //   height={height}
        //   language={language === 'hcl' ? 'hcl' : language}
        //   value={value}
        //   theme={isDark ? 'vs-dark' : 'vs-light'}
        //   onChange={(v) => onChange?.(v ?? '')}
        //   options={{ fontSize: 12, minimap: { enabled: false }, wordWrap: 'on', scrollBeyondLastLine: false }}
        // />
        <TextareaEditor value={value} onChange={onChange} height={height} />
      ) : (
        <CodeViewer
          code={value}
          language={language}
          showLineNumbers
          maxHeight={height}
        />
      )}
    </div>
  )
}
