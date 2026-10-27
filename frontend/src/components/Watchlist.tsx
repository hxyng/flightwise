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
  gate_change: 'text-primary',
  added: 'text-ok',
  removed: 'text-ink-48',
  tick: 'text-ink-48',
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
      <div className="glass-dark relative rounded-md p-3.5">
        {flash ? <div key={flash} className="flash-ring pointer-events-none absolute inset-0 rounded-md" /> : null}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <SplitFlap value={w.flight_number} size="md" />
            <div className="mt-1.5 flex items-center gap-1.5 text-sm text-body-muted">
              {s ? (
                <>
                  <span className="font-semibold text-white">{s.origin}</span>
                  <Plane className="size-3.5 text-body-muted" />
                  <span className="font-semibold text-white">{s.destination}</span>
                </>
              ) : (
                <span className="text-body-muted">{w.date}</span>
              )}
            </div>
          </div>
          <button onClick={onRemove} className="rounded-full p-1 text-body-muted hover:bg-white/10 hover:text-white" aria-label={`Stop watching ${w.flight_number}`}>
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
              <span className="inline-flex items-center gap-1 text-xs text-body-muted">
                <DoorOpen className="size-3.5" />
                <SplitFlap value={s.gate ?? '--'} size="sm" pad={3} />
              </span>
            </div>
            <div className="mt-2.5 flex items-center justify-between text-xs tabular-nums text-body-muted">
              <span className="inline-flex items-center gap-1">
                <PlaneTakeoff className="size-3.5" /> {hhmm(s.actual_departure ?? s.estimated_departure ?? s.scheduled_departure)}
              </span>
              <span className={delay >= 15 ? 'font-semibold text-warn' : delay > 0 ? 'text-white' : 'text-ok'}>{delay > 0 ? `+${delay}m` : 'on time'}</span>
              <span className="inline-flex items-center gap-1">
                <PlaneLanding className="size-3.5" /> {hhmm(s.actual_arrival ?? s.estimated_arrival ?? s.scheduled_arrival)}
              </span>
            </div>
            <div className="relative mt-2 h-1 overflow-hidden rounded-full bg-white/12">
              <motion.div className="absolute inset-y-0 left-0 rounded-full bg-white" animate={{ width: `${Math.round(progress * 100)}%` }} transition={{ duration: 1 }} />
            </div>
            {w.risk ? (
              <div className="mt-2 text-xs text-body-muted">
                Historic risk:{' '}
                <span className={w.risk.label === 'high' ? 'text-bad' : w.risk.label === 'medium' ? 'text-warn' : 'text-ok'}>
                  {w.risk.label} · {w.risk.pct_delayed_15.toFixed(0)}% late
                </span>
              </div>
            ) : null}
          </>
        ) : (
          <div className="mt-2 text-xs text-body-muted">Waiting for first status…</div>
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
        <h2 className="flex items-center gap-2 text-tagline font-semibold text-white">
          <Radar className="size-5 text-body-muted" /> Watchlist
          <span className="rounded-full bg-white/12 px-2 py-0.5 text-xs font-normal tabular-nums text-body-muted">{flights.length}</span>
        </h2>
        <span className={`inline-flex items-center gap-1.5 text-xs ${live ? 'text-ok' : 'text-warn'}`}>
          <span className={`size-2 rounded-full ${live ? 'bg-ok pulse-dot' : 'bg-warn'}`} /> {live ? 'Live' : 'Reconnecting'}
        </span>
      </div>

      <div className="space-y-3">
        <AnimatePresence initial={false}>
          {flights.map((w) => (
            <WatchCard key={w.id} w={w} flash={flashes[w.id] ?? 0} onRemove={() => onRemove(w.id)} />
          ))}
        </AnimatePresence>
        {flights.length === 0 ? (
          <div className="rounded-md border border-dashed border-white/15 p-4 text-center text-sm text-body-muted">
            No flights yet. Ask the agent to track one, or hit <span className="font-semibold text-primary">Watch</span> on a flight card.
          </div>
        ) : null}
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-body-muted">
          <BellRing className="size-3.5" /> Activity
        </h3>
        <div className="scrollbar-thin min-h-[8rem] flex-1 overflow-y-auto glass-dark rounded-md">
          {feed.length === 0 ? (
            <div className="p-4 text-sm text-body-muted">Gate, delay and status changes appear here as they happen.</div>
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
                      className="flex items-start gap-2.5 border-b border-white/8 px-3 py-2.5 text-sm last:border-0"
                    >
                      <Icon className={`mt-0.5 size-4 shrink-0 ${EVENT_TONE[e.type]}`} />
                      <div className="min-w-0 flex-1 text-[#f5f5f7]">{e.message}</div>
                      <span className="shrink-0 text-xs tabular-nums text-body-muted">{hhmm(e.ts)}</span>
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
