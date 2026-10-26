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

  return (
    <div className="glass rounded-2xl overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-line/70">
        <div className="flex items-center gap-2 font-mono text-lg font-bold">
          <span className="text-white">{first?.origin}</span>
          <Plane className="size-4 text-flap" />
          <span className="text-white">{first?.destination}</span>
          <span className="ml-2 text-sm font-normal text-slate-400">{offers.length} options</span>
        </div>
        <div className="flex flex-wrap gap-1">
          {KEYS.map(({ k, label }) => (
            <button
              key={k}
              onClick={() => (k === key ? setAsc(!asc) : (setKey(k), setAsc(true)))}
              className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold transition ${
                k === key ? 'bg-flap text-ink-950' : 'bg-ink-700 text-slate-300 hover:bg-ink-600'
              }`}
            >
              {label}
              {k === key ? <ArrowUpDown className={`size-3 ${asc ? '' : 'rotate-180'}`} /> : null}
            </button>
          ))}
        </div>
      </div>
      <ul className="divide-y divide-line/50">
        {sorted.map((o, i) => (
          <motion.li
            layout
            key={o.id}
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.05, layout: { duration: 0.35 } }}
            className="grid grid-cols-[1fr_auto] sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1.6fr)_auto] items-center gap-x-4 gap-y-1 px-4 py-3 hover:bg-white/[0.03]"
          >
            <div className="min-w-0">
              <div className="font-semibold text-white truncate">{o.airline}</div>
              <div className="font-mono text-xs text-flap">{o.flight_numbers.join(' · ')}</div>
            </div>
            <div className="text-right sm:hidden">
              <div className="font-mono text-xl font-bold text-white">{money(o.price, o.currency)}</div>
            </div>
            <div className="col-span-2 sm:col-span-1 flex items-center gap-3 font-mono">
              <span className="text-lg font-bold text-white">{hhmm(o.departure)}</span>
              <div className="flex-1 flex flex-col items-center min-w-[4rem]">
                <span className="text-[0.7rem] text-slate-400">{duration(o.duration_min)}</span>
                <div className="relative w-full h-px bg-slate-600">
                  {Array.from({ length: o.stops }).map((_, s) => (
                    <span key={s} className="absolute top-1/2 -translate-y-1/2 size-1.5 rounded-full bg-warn" style={{ left: `${((s + 1) / (o.stops + 1)) * 100}%` }} />
                  ))}
                </div>
                <span className={`text-[0.7rem] ${o.stops ? 'text-warn' : 'text-ok'}`}>{o.stops ? `${o.stops} stop${o.stops > 1 ? 's' : ''}` : 'nonstop'}</span>
              </div>
              <span className="text-lg font-bold text-white">{hhmm(o.arrival)}</span>
            </div>
            <div className="hidden sm:block text-right">
              <div className="font-mono text-2xl font-bold text-white">{money(o.price, o.currency)}</div>
              <div className="flex justify-end gap-1 mt-0.5">
                {o.recommended ? <span title={o.why} className="rounded bg-flap/20 px-1.5 text-[0.65rem] font-bold text-flap">AGENT PICK</span> : null}
                {o.price === cheapest ? <span className="rounded bg-ok/15 px-1.5 text-[0.65rem] font-bold text-ok">CHEAPEST</span> : null}
                {o.duration_min === fastest ? <span className="rounded bg-sky/15 px-1.5 text-[0.65rem] font-bold text-sky">FASTEST</span> : null}
              </div>
            </div>
          </motion.li>
        ))}
      </ul>
    </div>
  )
}
