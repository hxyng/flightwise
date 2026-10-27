import { Check, Copy } from 'lucide-react'
import { useState } from 'react'
import { highlightSql } from '../lib/format'

export function SqlBlock({ sql, className = '' }: { sql: string; className?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className={`on-dark relative rounded-sm bg-tile-1 ${className}`}>
      <button
        onClick={() => {
          navigator.clipboard?.writeText(sql).then(() => {
            setCopied(true)
            setTimeout(() => setCopied(false), 1200)
          }).catch(() => {})
        }}
        className="absolute right-2 top-2 rounded-sm p-1.5 text-body-muted hover:bg-white/10 hover:text-white"
        aria-label="Copy SQL"
      >
        {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
      </button>
      <pre className="scrollbar-thin overflow-x-auto p-4 pr-10 font-mono text-[13px] leading-relaxed tracking-normal text-[#f5f5f7]">
        <code dangerouslySetInnerHTML={{ __html: highlightSql(sql) }} />
      </pre>
    </div>
  )
}
