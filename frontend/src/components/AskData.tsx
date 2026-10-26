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
      <div className="glass rounded-2xl p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-white">Ask the data</h2>
            <p className="mt-1 text-slate-400">Plain English in, SQL out, run against US DOT on-time flight records.</p>
          </div>
          <span className="inline-flex flex-wrap items-center gap-2 rounded-full border border-sky/40 bg-gradient-to-r from-sky/15 to-flap/10 px-3 py-1.5 text-xs font-semibold text-slate-200">
            <Database className="size-3.5 text-sky" /> Powered by Snowflake
            <span className="text-slate-500">+</span>
            <Cpu className="size-3.5 text-flap" /> open-weight model running locally
          </span>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            run(q)
          }}
          className="mt-5 flex items-center gap-2 rounded-xl border border-line bg-ink-950/60 p-2 focus-within:border-flap/60"
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. Which airport has the longest delays in July?"
            className="min-w-0 flex-1 bg-transparent px-3 py-2.5 text-base sm:text-lg text-white placeholder:text-slate-500 outline-none"
            aria-label="Question for the data"
          />
          <button
            type="submit"
            disabled={!q.trim() || busy}
            className="grid size-11 place-items-center rounded-lg bg-flap text-ink-950 transition hover:brightness-110 disabled:opacity-40"
            aria-label="Ask"
          >
            {busy ? <Loader2 className="size-5 animate-spin" /> : <Send className="size-5" />}
          </button>
        </form>
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((e) => (
            <button
              key={e}
              disabled={busy}
              onClick={() => run(e)}
              className="inline-flex items-center gap-1.5 rounded-full border border-line bg-ink-800/70 px-3 py-1.5 text-sm text-slate-300 hover:border-flap/60 hover:text-white disabled:opacity-40"
            >
              <Sparkles className="size-3.5 text-flap" /> {e}
            </button>
          ))}
        </div>
      </div>

      {busy ? (
        <div className="glass relative mt-4 flex items-center gap-3 overflow-hidden rounded-2xl p-4 text-flap">
          <Loader2 className="size-5 animate-spin" />
          <span className="font-mono text-sm">translating to SQL → guard → running query…</span>
          <span className="scan-line pointer-events-none absolute inset-0" />
        </div>
      ) : null}
      {err ? <div className="mt-4 rounded-xl border border-bad/40 bg-bad/10 p-3 text-sm text-bad">{err}</div> : null}

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
