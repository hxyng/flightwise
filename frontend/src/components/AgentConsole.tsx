import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, Brain, CheckCircle2, ChevronRight, Database, Eye, ListChecks, Loader2, Plane, Search, Send, Sparkles, Square, Wrench } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { classify } from '../lib/format'
import type { AgentEvent, FlightStatus, HistoryMessage, WatchedFlight } from '../types'
import { FlightStatusCard } from './FlightStatusCard'
import { Markdown, TypedMarkdown } from './Markdown'
import { OfferList } from './OfferList'
import { QueryResultView } from './QueryResultView'
import { RiskGauge } from './RiskGauge'

export const SUGGESTIONS = [
  'Track AA100 and keep me posted',
  'Find me a flight OKC → DEN this Friday',
  "When's the best time to fly out of OKC?",
  'Which airline is most reliable?',
]

type Step =
  | { kind: 'thinking'; text: string }
  | { kind: 'tool'; name: string; args: unknown; result?: unknown; done: boolean; t0: number; ms?: number }
  | { kind: 'message'; text: string; streaming?: boolean; streamed?: boolean }
  | { kind: 'error'; text: string }

interface Turn {
  id: number
  user: string
  steps: Step[]
  running: boolean
}

const TOOL_META: Record<string, { label: string; icon: typeof Wrench }> = {
  track_flight: { label: 'Tracking live flight status', icon: Plane },
  search_flights: { label: 'Searching flights', icon: Search },
  query_delay_history: { label: 'Querying delay history in Snowflake', icon: Database },
  watch_flight: { label: 'Adding to watchlist', icon: Eye },
  list_watched: { label: 'Reading watchlist', icon: ListChecks },
}

function argSummary(args: unknown): string {
  if (!args || typeof args !== 'object') return args == null ? '' : String(args)
  return Object.entries(args as Record<string, unknown>)
    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join('  ')
}

function ToolResult({ name, result, watched, live, onWatch }: { name: string; result: unknown; watched: Set<string>; live: Map<string, FlightStatus>; onWatch: (fn: string) => Promise<void> }) {
  const c = classify(result)
  switch (c.kind) {
    case 'status':
      return <FlightStatusCard status={live.get(c.status.flight_number) ?? c.status} risk={c.risk} watched={watched.has(c.status.flight_number)} onWatch={onWatch} />
    case 'risk':
      return <RiskGauge risk={c.risk} />
    case 'offers':
      return <OfferList offers={c.offers} />
    case 'query':
      return <QueryResultView q={c.query} />
    case 'watched':
      return (
        <div className="flex flex-wrap gap-2">
          {c.flights.map((w) => (
            <span key={w.id} className="inline-flex items-center gap-2 rounded-lg bg-ok/10 px-3.5 py-2 text-sm text-ok">
              <Eye className="size-4" />
              <span className="font-semibold">{w.flight_number}</span>
              <span className="text-ink-80">{name === 'watch_flight' ? 'on your watchlist, live updates on' : w.date}</span>
            </span>
          ))}
        </div>
      )
    case 'error':
      return <div className="rounded-md bg-bad/8 px-3 py-2 text-sm text-bad">{c.text}</div>
    default:
      return (
        <pre className="scrollbar-thin max-h-48 overflow-auto rounded-sm bg-parchment p-3 font-mono text-xs tracking-normal text-ink-80">
          {typeof c.value === 'string' ? c.value : JSON.stringify(c.value, null, 2)}
        </pre>
      )
  }
}

const needsWorking = (s: Step) => (s.kind === 'tool' ? s.done : s.kind !== 'message' && s.kind !== 'error')

function useNow(ms = 100) {
  const [now, setNow] = useState(() => performance.now())
  useEffect(() => {
    const t = setInterval(() => setNow(performance.now()), ms)
    return () => clearInterval(t)
  }, [ms])
  return now
}

function Elapsed({ since, className = '' }: { since: number; className?: string }) {
  const now = useNow()
  return <span className={className}>{((now - since) / 1000).toFixed(1)}s</span>
}

const PHASES_START = ['Reading your request', 'Planning which tools to call', 'Reasoning on the local model']
const PHASES_AFTER = ['Reading tool results', 'Cross-checking delay history', 'Composing the answer']

/** Agent-is-working panel: cycling phase text, live timer, scanning bar. Stays lively through 5-10s waits. */
function Working({ afterTool }: { afterTool: boolean }) {
  const [t0] = useState(() => performance.now())
  const now = useNow(100)
  const secs = (now - t0) / 1000
  const phases = afterTool ? PHASES_AFTER : PHASES_START
  const phase = phases[Math.min(phases.length - 1, Math.floor(secs / 2.5))]
  return (
    <div className="glass-chip relative inline-flex max-w-full items-center gap-3 overflow-hidden rounded-full px-4 py-2">
      <Loader2 className="size-4 shrink-0 animate-spin text-primary" />
      <AnimatePresence mode="wait">
        <motion.span key={phase} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} className="text-sm text-ink">
          {phase}…
        </motion.span>
      </AnimatePresence>
      <span className="text-xs tabular-nums text-ink-48">{secs.toFixed(1)}s</span>
      <span className="hidden sm:flex h-4 items-end gap-0.5" aria-hidden>
        {[0, 1, 2, 3, 4].map((i) => (
          <motion.span key={i} className="w-1 rounded-full bg-ink/30" animate={{ height: ['20%', '100%', '35%', '80%', '20%'] }} transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.12 }} />
        ))}
      </span>
      <span className="scan-line pointer-events-none absolute inset-0" />
    </div>
  )
}

function ToolStep({ step, watched, live, onWatch }: { step: Extract<Step, { kind: 'tool' }>; watched: Set<string>; live: Map<string, FlightStatus>; onWatch: (fn: string) => Promise<void> }) {
  const meta = TOOL_META[step.name] ?? { label: step.name, icon: Wrench }
  const Icon = meta.icon
  return (
    <div className="space-y-2">
      <div
        className={`relative inline-flex max-w-full items-center gap-2 overflow-hidden rounded-full border px-3 py-1.5 text-sm ${
          step.done ? 'glass-chip text-ink' : 'border-primary/30 bg-white text-primary shadow-soft'
        }`}
      >
        {step.done ? <CheckCircle2 className="size-4 text-ok shrink-0" /> : <Loader2 className="size-4 animate-spin shrink-0" />}
        <Icon className="size-4 shrink-0 opacity-80" />
        <span className="font-semibold whitespace-nowrap">{meta.label}</span>
        <span className="font-mono text-xs tracking-normal text-ink-48 truncate">
          {step.name}({argSummary(step.args)})
        </span>
        {step.ms != null ? (
          <span className="text-xs tabular-nums text-ink-48 shrink-0">{(step.ms / 1000).toFixed(1)}s</span>
        ) : !step.done ? (
          <Elapsed since={step.t0} className="text-xs tabular-nums text-primary shrink-0" />
        ) : null}
        {!step.done ? <span className="scan-line pointer-events-none absolute inset-0" /> : null}
      </div>
      <AnimatePresence>
        {step.done && step.result !== undefined ? (
          <motion.div initial={{ opacity: 0, y: 10, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.4, ease: 'easeOut' }}>
            <ToolResult name={step.name} result={step.result} watched={watched} live={live} onWatch={onWatch} />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  )
}

export function AgentConsole({
  watched,
  live,
  onWatch,
  onAgentWatched,
}: {
  watched: Set<string>
  /** latest watcher status per flight number, so timeline cards update live */
  live: Map<string, FlightStatus>
  onWatch: (fn: string) => Promise<void>
  onAgentWatched: (w: WatchedFlight) => void
}) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [running, setRunning] = useState(false)
  const history = useRef<HistoryMessage[]>([])
  const abort = useRef<AbortController | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const content = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  // Follow the stream: stay pinned to the bottom while content grows, unless the user scrolled up.
  useEffect(() => {
    const el = scroller.current
    const inner = content.current
    if (!el || !inner) return
    let userAt = 0
    const onUser = () => {
      userAt = performance.now()
    }
    const onScroll = () => {
      // only user-initiated scrolls change stickiness, not our own smooth scrolling
      if (performance.now() - userAt < 1000) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 160
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    el.addEventListener('wheel', onUser, { passive: true })
    el.addEventListener('touchmove', onUser, { passive: true })
    el.addEventListener('pointerdown', onUser, { passive: true })
    const ro = new ResizeObserver(() => {
      if (stick.current) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    })
    ro.observe(inner)
    return () => {
      el.removeEventListener('scroll', onScroll)
      el.removeEventListener('wheel', onUser)
      el.removeEventListener('touchmove', onUser)
      el.removeEventListener('pointerdown', onUser)
      ro.disconnect()
    }
  }, [turns.length > 0])

  const patch = (id: number, fn: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)))

  async function send(text: string) {
    const msg = text.trim()
    if (!msg || running) return
    setInput('')
    const id = Date.now()
    stick.current = true
    setTurns((ts) => [...ts, { id, user: msg, steps: [], running: true }])
    setRunning(true)
    const ctl = new AbortController()
    abort.current = ctl

    const onEvent = (e: AgentEvent) => {
      const d = e.data ?? {}
      switch (e.type) {
        case 'thinking':
          patch(id, (t) => ({ ...t, steps: [...t.steps, { kind: 'thinking', text: String(d.text ?? '') }] }))
          break
        case 'tool_call':
          patch(id, (t) => ({ ...t, steps: [...t.steps, { kind: 'tool', name: String(d.name ?? 'tool'), args: d.arguments, done: false, t0: performance.now() }] }))
          break
        case 'tool_result': {
          const name = String(d.name ?? 'tool')
          const result = d.result
          if (name === 'watch_flight' && result && typeof result === 'object' && 'id' in result) onAgentWatched(result as WatchedFlight)
          patch(id, (t) => {
            const steps = [...t.steps]
            let i = steps.findIndex((s) => s.kind === 'tool' && !s.done && s.name === name)
            if (i < 0) i = steps.findIndex((s) => s.kind === 'tool' && !s.done)
            if (i >= 0) {
              const s = steps[i] as Extract<Step, { kind: 'tool' }>
              steps[i] = { ...s, done: true, result, ms: performance.now() - s.t0 }
            } else {
              steps.push({ kind: 'tool', name, args: undefined, result, done: true, t0: performance.now() })
            }
            return { ...t, steps }
          })
          break
        }
        case 'delta': {
          const piece = String(d.text ?? '')
          patch(id, (t) => {
            const last = t.steps[t.steps.length - 1]
            if (last && last.kind === 'message' && last.streaming) {
              return { ...t, steps: [...t.steps.slice(0, -1), { ...last, text: last.text + piece }] }
            }
            return { ...t, steps: [...t.steps, { kind: 'message', text: piece, streaming: true, streamed: true }] }
          })
          break
        }
        case 'message': {
          const full = String(d.text ?? '')
          patch(id, (t) => {
            const last = t.steps[t.steps.length - 1]
            if (last && last.kind === 'message' && last.streaming) {
              return { ...t, steps: [...t.steps.slice(0, -1), { ...last, text: full || last.text, streaming: false }] }
            }
            return { ...t, steps: [...t.steps, { kind: 'message', text: full }] }
          })
          break
        }
        case 'error':
          patch(id, (t) => ({ ...t, steps: [...t.steps, { kind: 'error', text: String(d.text ?? 'Agent error') }] }))
          break
        case 'done':
          if (Array.isArray(d.history)) history.current = d.history as HistoryMessage[]
          break
      }
    }

    try {
      await api.chat(msg, history.current, onEvent, ctl.signal)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        onEvent({ type: 'error', data: { text: `Connection problem: ${(err as Error).message}. Try ?mock=1 for the offline demo.` }, ts: new Date().toISOString() })
      }
    } finally {
      patch(id, (t) => ({ ...t, running: false, steps: t.steps.map((s) => (s.kind === 'tool' && !s.done ? { ...s, done: true } : s.kind === 'message' && s.streaming ? { ...s, streaming: false } : s)) }))
      setRunning(false)
      abort.current = null
      inputRef.current?.focus()
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scroller} className="scrollbar-thin flex-1 min-h-0 overflow-y-auto px-1 sm:px-2 pb-4">
        {turns.length === 0 ? (
          <div className="flex h-full min-h-[22rem] flex-col items-center justify-center-safe text-center px-4 py-10">
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="mb-3 inline-flex items-center gap-1.5 text-sm text-ink-48">
              <span className="size-1.5 rounded-full bg-ok" /> Agent console · online
            </motion.div>
            <motion.h2 initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="text-display-md sm:text-hero font-semibold text-ink">
              Where are we flying?
            </motion.h2>
            <p className="mt-4 max-w-xl text-ink-80 sm:text-tagline sm:font-normal sm:tracking-normal">An autonomous flight agent that tracks flights, watches them for you, and predicts delays from millions of real flights.</p>
            <div className="mt-10 grid w-full max-w-2xl grid-cols-1 sm:grid-cols-2 gap-3">
              {SUGGESTIONS.map((s, i) => (
                <motion.button
                  key={s}
                  initial={{ opacity: 0, y: 14 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 + i * 0.07 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => send(s)}
                  className="glass-chip group flex items-start gap-3 rounded-lg px-5 py-4 text-left text-base text-ink transition-shadow hover:shadow-card"
                >
                  <Sparkles className="mt-1 size-4 shrink-0 text-ink-48 group-hover:text-primary" />
                  <span className="flex-1">{s}</span>
                  <ChevronRight className="mt-1 size-4 shrink-0 text-primary" />
                </motion.button>
              ))}
            </div>
          </div>
        ) : (
          <div ref={content} className="space-y-8 pt-2">
            {turns.map((t) => (
              <div key={t.id} className="space-y-4">
                <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="flex justify-end">
                  <div className="max-w-[85%] rounded-lg rounded-br-xs bg-ink px-4 py-2.5 text-base text-white shadow-soft">{t.user}</div>
                </motion.div>
                <div className="relative space-y-4 border-l border-hairline pl-5 sm:pl-6 ml-2">
                  {t.steps.map((s, i) => (
                    <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }} className="relative">
                      <span
                        className={`absolute -left-[1.66rem] sm:-left-[1.91rem] top-2 size-2.5 rounded-full ring-4 ring-white ${
                          s.kind === 'error' ? 'bg-bad' : s.kind === 'message' ? 'bg-ink' : s.kind === 'thinking' ? 'bg-chip' : s.done ? 'bg-ok' : 'bg-primary pulse-dot'
                        }`}
                      />
                      {s.kind === 'thinking' ? (
                        <div className="flex items-start gap-2 text-sm text-ink-48">
                          <Brain className="mt-0.5 size-4 shrink-0 text-ink-48" />
                          <span>{s.text}</span>
                        </div>
                      ) : s.kind === 'tool' ? (
                        <ToolStep step={s} watched={watched} live={live} onWatch={onWatch} />
                      ) : s.kind === 'message' ? (
                        <div className="glass-chip rounded-lg rounded-tl-xs px-4 sm:px-5 py-3 text-base text-ink">
                          {s.streamed ? (
                            <div className={`md ${s.streaming ? 'caret' : ''}`}>
                              <Markdown text={s.text} />
                            </div>
                          ) : (
                            <TypedMarkdown text={s.text} />
                          )}
                        </div>
                      ) : (
                        <div className="flex items-start gap-2 rounded-md bg-bad/8 px-3 py-2 text-sm text-bad">
                          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                          {s.text}
                        </div>
                      )}
                    </motion.div>
                  ))}
                  {t.running && (t.steps.length === 0 || needsWorking(t.steps[t.steps.length - 1])) ? (
                    <div className="relative">
                      <span className="absolute -left-[1.66rem] sm:-left-[1.91rem] top-3.5 size-2.5 rounded-full bg-primary pulse-dot ring-4 ring-white" />
                      <Working afterTool={t.steps.some((s) => s.kind === 'tool')} />
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="pt-3">
        {turns.length > 0 ? (
          <div className="mb-2 flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                disabled={running}
                onClick={() => send(s)}
                className="chip shrink-0 px-3.5 py-1.5 text-ink-80 hover:text-ink"
              >
                {s}
              </button>
            ))}
          </div>
        ) : null}
        <form
          onSubmit={(e) => {
            e.preventDefault()
            send(input)
          }}
          className="search-field"
        >
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask FlightWise anything about your trip…"
            className="min-w-0 flex-1 bg-transparent px-3 py-2 text-base text-ink placeholder:text-ink-48 outline-none"
            aria-label="Message the agent"
          />
          {running ? (
            <button type="button" onClick={() => abort.current?.abort()} className="grid size-10 shrink-0 place-items-center rounded-full bg-chip/64 text-ink hover:bg-chip" aria-label="Stop">
              <Square className="size-4" />
            </button>
          ) : (
            <button type="submit" disabled={!input.trim()} className="btn-primary size-10 shrink-0 hover:bg-primary-focus" aria-label="Send">
              <Send className="size-4" />
            </button>
          )}
        </form>
      </div>
    </div>
  )
}
