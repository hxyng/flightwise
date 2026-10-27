import { motion } from 'framer-motion'
import { Cpu, Database, Loader2, Send, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import type { QueryResult } from '../types'
import { QueryResultView } from './QueryResultView'

const EXAMPLES = [
  'Which airline is most reliable out of OKC?',
  'What hour of the day has the fewest delays?',
  'Which month has the worst delays?',
  'Average departure delay by carrier at DFW',
]

export function AskData() {
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<{ id: number; r: QueryResult }[]>([])
  const [err, setErr] = useState<string | null>(null)

  async function run(question: string) {
    const text = question.trim()
    if (!text || busy) return
    setBusy(true)
    setErr(null)
    setQ('')
    try {
      const r = await api.ask(text)
      setResults((rs) => [{ id: Date.now(), r }, ...rs])
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="scrollbar-thin h-full min-h-0 overflow-y-auto px-1 pb-6">
      <div className="glass-chip rounded-lg p-4 sm:p-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lead sm:text-display-md font-semibold text-ink">Ask the data</h2>
            <p className="mt-1 text-ink-80">Plain English in, SQL out, run against US DOT on-time flight records.</p>
          </div>
          <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg bg-white px-3 py-1.5 text-xs text-ink-80 shadow-soft sm:rounded-full">
            <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
              <Database className="size-3.5 text-ink-48" /> Powered by Snowflake
            </span>
            <span className="text-ink-48">+</span>
            <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
              <Cpu className="size-3.5 text-ink-48" /> open-weight model running locally
            </span>
          </span>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            run(q)
          }}
          className="search-field mt-5"
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. Which airport has the longest delays in July?"
            className="min-w-0 flex-1 bg-transparent px-3 py-2 text-base text-ink placeholder:text-ink-48 outline-none"
            aria-label="Question for the data"
          />
          <button
            type="submit"
            disabled={!q.trim() || busy}
            className="btn-primary size-10 shrink-0 hover:bg-primary-focus"
            aria-label="Ask"
          >
            {busy ? <Loader2 className="size-5 animate-spin" /> : <Send className="size-5" />}
          </button>
        </form>
        <div className="-mx-4 mt-3 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 [&::-webkit-scrollbar]:hidden">
          {EXAMPLES.map((e) => (
            <button
              key={e}
              disabled={busy}
              onClick={() => run(e)}
              className="chip shrink-0 whitespace-nowrap px-3.5 py-1.5 text-ink-80 hover:text-ink"
            >
              <Sparkles className="size-3.5 text-ink-48" /> {e}
            </button>
          ))}
        </div>
      </div>

      {busy ? (
        <div className="card relative mt-4 flex items-center gap-3 overflow-hidden p-4 text-ink-80">
          <Loader2 className="size-5 animate-spin text-primary" />
          <span className="text-sm">translating to SQL → guard → running query…</span>
          <span className="scan-line pointer-events-none absolute inset-0" />
        </div>
      ) : null}
      {err ? <div className="mt-4 rounded-md bg-bad/8 p-3 text-sm text-bad">{err}</div> : null}

      <div className="mt-4 space-y-4">
        {results.map(({ id, r }) => (
          <motion.div key={id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <QueryResultView q={r} />
          </motion.div>
        ))}
      </div>
    </div>
  )
}
