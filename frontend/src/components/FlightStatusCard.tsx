import { Check, DoorOpen, Eye, Loader2 } from 'lucide-react'
import { useState } from 'react'
import type { DelayRisk, FlightStatus } from '../types'
import { hhmm, phaseLabel, phaseTone, TONE_DOT, TONE_TEXT } from '../lib/format'
import { RouteArc } from './RouteArc'
import { SplitFlap } from './SplitFlap'
import { RiskGauge } from './RiskGauge'

// on-dark data colors, matching .on-dark in index.css
const TONE_HEX: Record<string, string> = { ok: '#30d158', warn: '#ffb340', bad: '#ff6961', sky: '#2997ff', dim: '#8e8e93' }

function TimeCol({ label, sched, est, act, align = 'left' }: { label: string; sched?: string | null; est?: string | null; act?: string | null; align?: 'left' | 'right' }) {
  const shown = act ?? est ?? sched
  const changed = !!sched && !!shown && hhmm(shown) !== hhmm(sched)
  return (
    <div className={align === 'right' ? 'text-right' : ''}>
      <div className="text-xs text-ink-48">{label}</div>
      <div className={`font-display text-lead font-semibold tabular-nums ${changed ? 'text-warn' : 'text-ink'}`}>{hhmm(shown)}</div>
      {changed ? <div className="text-xs tabular-nums text-ink-48 line-through">{hhmm(sched)}</div> : <div className="text-xs text-ink-48">{act ? 'actual' : est ? 'estimated' : 'scheduled'}</div>}
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
    <div className="card overflow-hidden">
      <div className="on-dark bg-tile-1 px-4 sm:px-6 pt-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <SplitFlap value={status.flight_number} size="lg" />
            <div className="mt-1.5 truncate text-sm text-body-muted">
              {status.airline ?? status.airline_code ?? ''}
              {status.aircraft ? ` · ${status.aircraft}` : ''}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={`size-2.5 rounded-full ${TONE_DOT[tone]} pulse-dot`} />
            <SplitFlap value={phaseLabel(status.status)} size="md" pad={9} tone={TONE_TEXT[tone]} />
          </div>
        </div>

        <div className="pt-3 pb-4">
          <div className="flex items-end justify-between">
            <div className="font-display text-display-lg sm:text-hero font-semibold tabular-nums text-white">{status.origin}</div>
            <div className="font-display text-display-lg sm:text-hero font-semibold tabular-nums text-white">{status.destination}</div>
          </div>
          <div className="-mt-4 sm:-mt-6 px-6 sm:px-10">
            <RouteArc progress={progress} origin={status.origin} destination={status.destination} tone={TONE_HEX[tone]} />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 px-4 sm:px-6 py-5">
        <TimeCol label="Departs" sched={status.scheduled_departure} est={status.estimated_departure} act={status.actual_departure} />
        <TimeCol label="Arrives" sched={status.scheduled_arrival} est={status.estimated_arrival} act={status.actual_arrival} />
        <div>
          <div className="text-xs text-ink-48">Gate</div>
          <div className="flex items-center gap-2 mt-1">
            <DoorOpen className="size-4 text-ink-48" />
            <SplitFlap value={status.gate ?? '--'} size="md" pad={3} />
          </div>
          {status.terminal ? <div className="text-xs text-ink-48 mt-1">Terminal {status.terminal}</div> : null}
        </div>
        <div>
          <div className="text-xs text-ink-48">Delay</div>
          <div className={`font-display text-lead font-semibold tabular-nums ${delay >= 15 ? 'text-warn' : delay > 0 ? 'text-ink' : 'text-ok'}`}>
            {delay > 0 ? `+${delay}m` : 'On time'}
          </div>
          <div className="text-xs text-ink-48">{Math.round(progress * 100)}% of trip</div>
        </div>
      </div>

      {risk && !compact ? (
        <div className="border-t border-divider px-4 sm:px-6 py-5">
          <RiskGauge risk={risk} embedded />
        </div>
      ) : null}

      {onWatch ? (
        <div className="flex items-center justify-between gap-3 bg-parchment px-4 sm:px-6 py-3">
          <div className="text-xs text-ink-48">
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
            className={`inline-flex items-center gap-2 rounded-full px-5 py-2 text-sm ${
              watched ? 'bg-white text-ok shadow-soft' : 'btn-primary hover:bg-primary-focus'
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
