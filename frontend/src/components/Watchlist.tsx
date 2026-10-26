import { AnimatePresence, motion } from 'framer-motion'
import { Activity, BellRing, Clock, DoorOpen, Eye, Plane, PlaneLanding, PlaneTakeoff, Radar, X } from 'lucide-react'
import type { WatchEvent, WatchedFlight } from '../types'
import { hhmm, phaseLabel, phaseTone, TONE_DOT, TONE_TEXT } from '../lib/format'
import { SplitFlap } from './SplitFlap'

export const EVENT_ICON: Record<string, typeof Plane> = {
  status_change: PlaneTakeoff,
  delay_change: Clock,
  gate_change: DoorOpen,
  added: Eye,
  removed: X,
  tick: Activity,
}
export const EVENT_TONE: Record<string, string> = {
  status_change: 'text-sky',
  delay_change: 'text-warn',
  gate_change: 'text-flap',
  added: 'text-ok',
  removed: 'text-slate-400',
  tick: 'text-slate-400',
}

function WatchCard({ w, flash, onRemove }: { w: WatchedFlight; flash: number; onRemove: () => void }) {
  const s = w.last_status
  const tone = s ? phaseTone(s.status, s.departure_delay_min) : 'dim'
  const progress = s?.progress ?? (s?.status === 'landed' ? 1 : 0)
  const delay = s?.departure_delay_min ?? 0
  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 30, scale: 0.96 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 30, scale: 0.96 }}
      transition={{ type: 'spring', stiffness: 260, damping: 26 }}
      key={w.id}
      className="relative"
    >
      <div className="glass relative rounded-xl p-3">
        {flash ? <div key={flash} className="flash-amber pointer-events-none absolute inset-0 rounded-xl" /> : null}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <SplitFlap value={w.flight_number} size="md" />
            <div className="mt-1 flex items-center gap-1.5 font-mono text-sm text-slate-300">
              {s ? (
                <>
                  <span className="font-bold text-white">{s.origin}</span>
                  <Plane className="size-3.5 text-slate-500" />
                  <span className="font-bold text-white">{s.destination}</span>
                </>
              ) : (
                <span className="text-slate-500">{w.date}</span>
              )}
            </div>
          </div>
          <button onClick={onRemove} className="rounded-md p-1 text-slate-500 hover:bg-ink-600 hover:text-white" aria-label={`Stop watching ${w.flight_number}`}>
            <X className="size-4" />
          </button>
        </div>
        {s ? (
          <>
            <div className="mt-2 flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5">
                <span className={`size-2 rounded-full ${TONE_DOT[tone]} pulse-dot`} />
                <SplitFlap value={phaseLabel(s.status)} size="sm" pad={9} tone={TONE_TEXT[tone]} />
              </span>
              <span className="inline-flex items-center gap-1 text-xs text-slate-400">
                <DoorOpen className="size-3.5" />
                <SplitFlap value={s.gate ?? '--'} size="sm" pad={3} />
              </span>
            </div>
            <div className="mt-2 flex items-center justify-between font-mono text-xs text-slate-400">
              <span className="inline-flex items-center gap-1">
                <PlaneTakeoff className="size-3.5" /> {hhmm(s.actual_departure ?? s.estimated_departure ?? s.scheduled_departure)}
              </span>
              <span className={delay >= 15 ? 'font-bold text-warn' : delay > 0 ? 'text-slate-200' : 'text-ok'}>{delay > 0 ? `+${delay}m` : 'on time'}</span>
              <span className="inline-flex items-center gap-1">
                <PlaneLanding className="size-3.5" /> {hhmm(s.actual_arrival ?? s.estimated_arrival ?? s.scheduled_arrival)}
              </span>
            </div>
            <div className="relative mt-2 h-1.5 overflow-hidden rounded-full bg-ink-600">
              <motion.div className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-flap/40 to-flap" animate={{ width: `${Math.round(progress * 100)}%` }} transition={{ duration: 1 }} />
            </div>
            {w.risk ? (
              <div className="mt-2 text-[0.7rem] text-slate-500">
                Historic risk:{' '}
                <span className={w.risk.label === 'high' ? 'text-bad' : w.risk.label === 'medium' ? 'text-warn' : 'text-ok'}>
                  {w.risk.label} · {w.risk.pct_delayed_15.toFixed(0)}% late
                </span>
              </div>
            ) : null}
          </>
        ) : (
          <div className="mt-2 text-xs text-slate-500">Waiting for first status…</div>
        )}
      </div>
    </motion.div>
  )
}

export function Watchlist({
  flights,
  feed,
  flashes,
  live,
  onRemove,
}: {
  flights: WatchedFlight[]
  feed: WatchEvent[]
  flashes: Record<string, number>
  live: boolean
  onRemove: (id: string) => void
}) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-[0.25em] text-slate-300">
          <Radar className="size-4 text-flap" /> Watchlist
          <span className="rounded-full bg-ink-600 px-2 py-0.5 font-mono text-xs tracking-normal text-slate-300">{flights.length}</span>
        </h2>
        <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${live ? 'text-ok' : 'text-warn'}`}>
          <span className={`size-2 rounded-full ${live ? 'bg-ok pulse-dot' : 'bg-warn'}`} /> {live ? 'LIVE' : 'RECONNECTING'}
        </span>
      </div>

      <div className="space-y-3">
        <AnimatePresence initial={false}>
          {flights.map((w) => (
            <WatchCard key={w.id} w={w} flash={flashes[w.id] ?? 0} onRemove={() => onRemove(w.id)} />
          ))}
        </AnimatePresence>
        {flights.length === 0 ? (
          <div className="rounded-xl border border-dashed border-line p-4 text-center text-sm text-slate-500">
            No flights yet. Ask the agent to track one, or hit <span className="font-semibold text-flap">Watch</span> on a flight card.
          </div>
        ) : null}
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <h3 className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.25em] text-slate-400">
          <BellRing className="size-3.5" /> Activity
        </h3>
        <div className="scrollbar-thin min-h-[8rem] flex-1 overflow-y-auto rounded-xl border border-line/60 bg-ink-900/50">
          {feed.length === 0 ? (
            <div className="p-4 text-sm text-slate-500">Gate, delay and status changes appear here as they happen.</div>
          ) : (
            <ul>
              <AnimatePresence initial={false}>
                {feed.map((e) => {
                  const Icon = EVENT_ICON[e.type] ?? Activity
                  return (
                    <motion.li
                      key={`${e.ts}-${e.flight_id}-${e.type}`}
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      className="flex items-start gap-2.5 border-b border-line/40 px-3 py-2 text-sm last:border-0"
                    >
                      <Icon className={`mt-0.5 size-4 shrink-0 ${EVENT_TONE[e.type]}`} />
                      <div className="min-w-0 flex-1 text-slate-200">{e.message}</div>
                      <span className="shrink-0 font-mono text-[0.7rem] text-slate-500">{hhmm(e.ts)}</span>
                    </motion.li>
                  )
                })}
              </AnimatePresence>
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
