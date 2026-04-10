import { useState } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Copy, Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/store/themeStore'

interface Props {
  code: string
  language?: string
  filename?: string
  maxHeight?: string
  className?: string
  showLineNumbers?: boolean
}

export function CodeViewer({
  code,
  language = 'text',
  filename,
  maxHeight,
  className,
  showLineNumbers = true,
}: Props) {
  const [copied, setCopied] = useState(false)
  const isDark = useThemeStore((s) => s.theme === 'dark')

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const syntaxStyle = isDark ? oneDark : oneLight
  const bgColor     = isDark ? 'rgb(8 15 31)' : '#fafafa'
  const lineNumColor = isDark ? '#334155' : '#94a3b8'

  return (
    <div className={cn('relative group', className)}>
      {/* Header */}
      {filename && (
        <div className={cn(
          'flex items-center justify-between px-4 py-2',
          'bg-slate-100 dark:bg-surface-800/60',
          'border-b border-slate-200 dark:border-white/[0.04]'
        )}>
          <span className="text-xs font-mono text-slate-500 dark:text-slate-400">{filename}</span>
          <span className={cn(
            'text-xs font-mono px-2 py-0.5 rounded',
            'text-slate-400 dark:text-slate-600',
            'bg-slate-200 dark:bg-surface-700/50'
          )}>
            {language}
          </span>
        </div>
      )}

      {/* Copy button */}
      <button
        onClick={handleCopy}
        className={cn(
          'absolute right-3 p-1.5 rounded-md transition-all z-10',
          'opacity-0 group-hover:opacity-100',
          filename ? 'top-11' : 'top-3',
          'bg-slate-200 dark:bg-surface-700/80',
          'text-slate-500 dark:text-slate-400',
          'hover:text-slate-900 dark:hover:text-white'
        )}
        title="Copy to clipboard"
      >
        {copied
          ? <Check className="w-3.5 h-3.5 text-emerald-500" />
          : <Copy  className="w-3.5 h-3.5" />}
      </button>

      {/* Code */}
      <div className="overflow-auto" style={maxHeight ? { maxHeight } : undefined}>
        <SyntaxHighlighter
          language={language}
          style={syntaxStyle}
          showLineNumbers={showLineNumbers}
          customStyle={{
            margin: 0,
            borderRadius: 0,
            background: bgColor,
            fontSize: '0.75rem',
            lineHeight: '1.6',
          }}
          lineNumberStyle={{ color: lineNumColor, minWidth: '2.5em' }}
        >
          {code}
        </SyntaxHighlighter>
      </div>
    </div>
  )
}
