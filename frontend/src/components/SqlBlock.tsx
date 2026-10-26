import { Check, Copy } from 'lucide-react'
import { useState } from 'react'
import { highlightSql } from '../lib/format'

export function SqlBlock({ sql, className = '' }: { sql: string; className?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className={`relative rounded-xl border border-line bg-ink-950/80 ${className}`}>
      <button
        onClick={() => {
          navigator.clipboard?.writeText(sql).then(() => {
            setCopied(true)
            setTimeout(() => setCopied(false), 1200)
          }).catch(() => {})
        }}
        className="absolute right-2 top-2 rounded-md p-1.5 text-slate-500 hover:text-flap hover:bg-ink-700"
        aria-label="Copy SQL"
      >
        {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
      </button>
      <pre className="scrollbar-thin overflow-x-auto p-4 pr-10 font-mono text-[0.8rem] leading-relaxed text-slate-300">
        <code dangerouslySetInnerHTML={{ __html: highlightSql(sql) }} />
      </pre>
    </div>
  )
}
