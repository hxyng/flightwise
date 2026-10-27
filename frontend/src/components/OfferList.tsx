import { ArrowUpDown, Plane } from 'lucide-react'
import { motion } from 'framer-motion'
import { useMemo, useState } from 'react'
import type { FlightOffer } from '../types'
import { duration, hhmm, money } from '../lib/format'

type Key = 'price' | 'duration' | 'departure' | 'stops'
const KEYS: { k: Key; label: string }[] = [
  { k: 'price', label: 'Price' },
  { k: 'duration', label: 'Duration' },
  { k: 'departure', label: 'Depart' },
  { k: 'stops', label: 'Stops' },
]

function val(o: FlightOffer, k: Key): number {
  if (k === 'price') return o.price ?? Number.POSITIVE_INFINITY
  if (k === 'duration') return o.duration_min
  if (k === 'stops') return o.stops * 10000 + (o.price ?? 0)
  return new Date(o.departure).getTime()
}

export function OfferList({ offers }: { offers: FlightOffer[] }) {
  const [key, setKey] = useState<Key>('price')
  const [asc, setAsc] = useState(true)
  const sorted = useMemo(() => [...offers].sort((a, b) => (val(a, key) - val(b, key)) * (asc ? 1 : -1)), [offers, key, asc])
  const cheapest = Math.min(...offers.map((o) => o.price ?? Number.POSITIVE_INFINITY))
  const fastest = Math.min(...offers.map((o) => o.duration_min))
  const first = offers[0]

  const badges = (o: FlightOffer) => (
    <>
      {o.recommended ? <span title={o.why} className="rounded-full bg-ink px-2 py-0.5 text-[11px] font-semibold tracking-normal text-white">AGENT PICK</span> : null}
      {o.price === cheapest ? <span className="rounded-full bg-ok/10 px-2 py-0.5 text-[11px] font-semibold tracking-normal text-ok">CHEAPEST</span> : null}
      {o.duration_min === fastest ? <span className="rounded-full bg-parchment px-2 py-0.5 text-[11px] font-semibold tracking-normal text-ink-80 ring-1 ring-inset ring-black/10">FASTEST</span> : null}
    </>
  )

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 sm:px-6 py-4 border-b border-divider">
        <div className="flex items-center gap-2 font-display text-tagline font-semibold">
          <span className="text-ink">{first?.origin}</span>
          <Plane className="size-4 text-ink-48" />
          <span className="text-ink">{first?.destination}</span>
          <span className="ml-2 text-sm font-normal text-ink-48">{offers.length} options</span>
        </div>
        <div className="glass-chip flex gap-0.5 rounded-full p-1">
          {KEYS.map(({ k, label }) => (
            <button
              key={k}
              onClick={() => (k === key ? setAsc(!asc) : (setKey(k), setAsc(true)))}
              className={`inline-flex items-center gap-1 rounded-full px-2.5 sm:px-3 py-1 text-xs ${
                k === key ? 'bg-ink font-semibold text-white shadow-soft' : 'text-ink-80 hover:text-ink'
              }`}
            >
              {label}
              {k === key ? <ArrowUpDown className={`size-3 ${asc ? '' : 'rotate-180'}`} /> : null}
            </button>
          ))}
        </div>
      </div>
      <ul className="divide-y divide-divider">
        {sorted.map((o, i) => (
          <motion.li
            layout
            key={o.id}
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.05, layout: { duration: 0.35 } }}
            className={`grid grid-cols-[1fr_auto] sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1.6fr)_auto] items-center gap-x-4 gap-y-1 px-4 sm:px-6 py-3.5 ${o.recommended ? 'bg-pearl' : ''}`}
          >
            <div className="min-w-0">
              <div className="font-semibold text-ink truncate">{o.airline}</div>
              <div className="text-xs tabular-nums text-ink-48">{o.flight_numbers.join(' · ')}</div>
            </div>
            <div className="text-right sm:hidden">
              <div className="font-display text-tagline font-semibold tabular-nums text-ink">{money(o.price, o.currency)}</div>
              <div className="flex flex-wrap justify-end gap-1 mt-0.5">{badges(o)}</div>
            </div>
            <div className="col-span-2 sm:col-span-1 flex items-center gap-3 tabular-nums">
              <span className="text-base font-semibold text-ink">{hhmm(o.departure)}</span>
              <div className="flex-1 flex flex-col items-center min-w-[4rem]">
                <span className="text-xs text-ink-48">{duration(o.duration_min)}</span>
                <div className="relative w-full h-px bg-chip">
                  {Array.from({ length: o.stops }).map((_, s) => (
                    <span key={s} className="absolute top-1/2 -translate-y-1/2 size-1.5 rounded-full bg-warn" style={{ left: `${((s + 1) / (o.stops + 1)) * 100}%` }} />
                  ))}
                </div>
                <span className={`text-xs ${o.stops ? 'text-warn' : 'text-ok'}`}>{o.stops ? `${o.stops} stop${o.stops > 1 ? 's' : ''}` : 'Nonstop'}</span>
              </div>
              <span className="text-base font-semibold text-ink">{hhmm(o.arrival)}</span>
            </div>
            <div className="hidden sm:block text-right">
              <div className="font-display text-lead font-semibold tabular-nums text-ink">{money(o.price, o.currency)}</div>
              <div className="flex justify-end gap-1 mt-1">{badges(o)}</div>
            </div>
          </motion.li>
        ))}
      </ul>
    </div>
  )
}
