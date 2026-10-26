import { Check, DoorOpen, Eye, Loader2, Plane } from 'lucide-react'
import { useState } from 'react'
import type { DelayRisk, FlightStatus } from '../types'
import { hhmm, phaseLabel, phaseTone, TONE_DOT, TONE_TEXT } from '../lib/format'
import { RouteArc } from './RouteArc'
import { SplitFlap } from './SplitFlap'
import { RiskGauge } from './RiskGauge'

const TONE_HEX: Record<string, string> = { ok: '#34d399', warn: '#fbbf24', bad: '#f87171', sky: '#38bdf8', dim: '#94a3b8' }

function TimeCol({ label, sched, est, act, align = 'left' }: { label: string; sched?: string | null; est?: string | null; act?: string | null; align?: 'left' | 'right' }) {
  const shown = act ?? est ?? sched
  const changed = !!sched && !!shown && hhmm(shown) !== hhmm(sched)
  return (
    <div className={align === 'right' ? 'text-right' : ''}>
      <div className="text-[0.65rem] uppercase tracking-[0.2em] text-slate-400">{label}</div>
      <div className={`font-mono text-2xl sm:text-3xl font-bold ${changed ? 'text-warn' : 'text-white'}`}>{hhmm(shown)}</div>
      {changed ? <div className="font-mono text-xs text-slate-500 line-through">{hhmm(sched)}</div> : <div className="text-xs text-slate-500">{act ? 'actual' : est ? 'estimated' : 'scheduled'}</div>}
    </div>
  )
}

/** Boarding-pass style live status card. */
export function FlightStatusCard({
  status,
  risk,
  watched,
  onWatch,
  compact = false,
}: {
  status: FlightStatus
  risk?: DelayRisk | null
  watched?: boolean
  onWatch?: (fn: string) => Promise<void>
  compact?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const tone = phaseTone(status.status, status.departure_delay_min)
  const delay = status.departure_delay_min ?? 0
  const progress = status.progress ?? (status.status === 'landed' ? 1 : 0)

  return (
    <div className="glass rounded-2xl overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 sm:px-5 pt-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="grid place-items-center size-10 rounded-xl bg-flap/10 border border-flap/30 shrink-0">
            <Plane className="size-5 text-flap" />
          </div>
          <div className="min-w-0">
            <SplitFlap value={status.flight_number} size="lg" />
            <div className="text-sm text-slate-400 truncate mt-1">
              {status.airline ?? status.airline_code ?? ''}
              {status.aircraft ? ` · ${status.aircraft}` : ''}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`size-2.5 rounded-full ${TONE_DOT[tone]} pulse-dot`} />
          <SplitFlap value={phaseLabel(status.status)} size="md" pad={9} tone={TONE_TEXT[tone]} />
        </div>
      </div>

      <div className="px-4 sm:px-5 pt-2">
        <div className="flex items-end justify-between">
          <div className="font-mono text-4xl sm:text-5xl font-extrabold tracking-tight text-white">{status.origin}</div>
          <div className="font-mono text-4xl sm:text-5xl font-extrabold tracking-tight text-white">{status.destination}</div>
        </div>
        <div className="-mt-4 sm:-mt-6 px-6 sm:px-10">
          <RouteArc progress={progress} origin={status.origin} destination={status.destination} tone={TONE_HEX[tone]} />
        </div>
      </div>

      {/* perforation */}
      <div className="relative my-1 h-4">
        <div className="absolute -left-2 top-0 size-4 rounded-full bg-ink-950" />
        <div className="absolute -right-2 top-0 size-4 rounded-full bg-ink-950" />
        <div className="absolute left-4 right-4 top-2 border-t border-dashed border-line" />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 px-4 sm:px-5 pb-4">
        <TimeCol label="Departs" sched={status.scheduled_departure} est={status.estimated_departure} act={status.actual_departure} />
        <TimeCol label="Arrives" sched={status.scheduled_arrival} est={status.estimated_arrival} act={status.actual_arrival} />
        <div>
          <div className="text-[0.65rem] uppercase tracking-[0.2em] text-slate-400">Gate</div>
          <div className="flex items-center gap-2 mt-1">
            <DoorOpen className="size-4 text-slate-400" />
            <SplitFlap value={status.gate ?? '--'} size="md" pad={3} />
          </div>
          {status.terminal ? <div className="text-xs text-slate-500 mt-1">Terminal {status.terminal}</div> : null}
        </div>
        <div>
          <div className="text-[0.65rem] uppercase tracking-[0.2em] text-slate-400">Delay</div>
          <div className={`font-mono text-2xl sm:text-3xl font-bold ${delay >= 15 ? 'text-warn' : delay > 0 ? 'text-slate-200' : 'text-ok'}`}>
            {delay > 0 ? `+${delay}m` : 'ON TIME'}
          </div>
          <div className="text-xs text-slate-500">{Math.round(progress * 100)}% of trip</div>
        </div>
      </div>

      {risk && !compact ? (
        <div className="border-t border-line/70 px-4 sm:px-5 py-4">
          <RiskGauge risk={risk} embedded />
        </div>
      ) : null}

      {onWatch ? (
        <div className="flex items-center justify-between gap-3 border-t border-line/70 bg-ink-900/40 px-4 sm:px-5 py-3">
          <div className="text-xs text-slate-500 font-mono">
            src: {status.source} · updated {hhmm(status.updated_at)}
          </div>
          <button
            disabled={watched || busy}
            onClick={async () => {
              setBusy(true)
              try {
                await onWatch(status.flight_number)
              } finally {
                setBusy(false)
              }
            }}
            className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-semibold transition ${
              watched ? 'bg-ok/15 text-ok border border-ok/40' : 'bg-flap text-ink-950 hover:brightness-110 active:scale-95'
            }`}
          >
            {busy ? <Loader2 className="size-4 animate-spin" /> : watched ? <Check className="size-4" /> : <Eye className="size-4" />}
            {watched ? 'Watching' : 'Watch'}
          </button>
        </div>
      ) : null}
    </div>
  )
}
