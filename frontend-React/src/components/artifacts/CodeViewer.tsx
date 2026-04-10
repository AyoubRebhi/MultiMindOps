import { useState } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Copy, Check } from 'lucide-react'
import { cn } from '@/lib/utils'

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

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className={cn('relative group', className)}>
      {/* Header */}
      {filename && (
        <div className="flex items-center justify-between px-4 py-2 bg-surface-800/60 border-b border-white/[0.04]">
          <span className="text-xs font-mono text-slate-400">{filename}</span>
          <span className="text-xs text-slate-600 bg-surface-700/50 px-2 py-0.5 rounded font-mono">
            {language}
          </span>
        </div>
      )}

      {/* Copy button */}
      <button
        onClick={handleCopy}
        className={cn(
          'absolute right-3 top-3 p-1.5 rounded-md transition-all z-10',
          filename ? 'top-11' : 'top-3',
          'bg-surface-700/80 text-slate-400 hover:text-white opacity-0 group-hover:opacity-100'
        )}
        title="Copy to clipboard"
      >
        {copied ? (
          <Check className="w-3.5 h-3.5 text-emerald-400" />
        ) : (
          <Copy className="w-3.5 h-3.5" />
        )}
      </button>

      {/* Code */}
      <div
        className="overflow-auto"
        style={maxHeight ? { maxHeight } : undefined}
      >
        <SyntaxHighlighter
          language={language}
          style={oneDark}
          showLineNumbers={showLineNumbers}
          customStyle={{
            margin: 0,
            borderRadius: 0,
            background: 'rgb(8 15 31)',
            fontSize: '0.75rem',
            lineHeight: '1.6',
          }}
          lineNumberStyle={{ color: '#334155', minWidth: '2.5em' }}
        >
          {code}
        </SyntaxHighlighter>
      </div>
    </div>
  )
}
