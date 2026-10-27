import { Code2, Database } from 'lucide-react'
import { useState } from 'react'
import { motion } from 'framer-motion'
import type { DelayRisk } from '../types'
import { SqlBlock } from './SqlBlock'

const LABEL: Record<DelayRisk['label'], { color: string; text: string }> = {
  low: { color: '#248a3d', text: 'Low risk' },
  medium: { color: '#a85b00', text: 'Medium risk' },
  high: { color: '#d70015', text: 'High risk' },
  unknown: { color: '#6e6e73', text: 'Not enough data' },
}

const MAX = 50 // gauge full scale, % delayed 15+

/** Semicircle meter for historical delay odds. */
export function RiskGauge({ risk, embedded = false }: { risk: DelayRisk; embedded?: boolean }) {
  const [showSql, setShowSql] = useState(false)
  const { color, text } = LABEL[risk.label] ?? LABEL.unknown
  const frac = Math.max(0, Math.min(1, risk.pct_delayed_15 / MAX))
  const R = 70
  const C = Math.PI * R
  const needle = -90 + frac * 180

  const ctx = [risk.carrier, `from ${risk.origin}`, risk.hour != null ? `${String(risk.hour).padStart(2, '0')}:00 departures` : null, risk.month != null ? `month ${risk.month}` : null]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className={embedded ? '' : 'card p-4 sm:p-6'}>
      <div className="flex flex-col sm:flex-row items-center gap-4 sm:gap-6">
        <svg viewBox="0 0 180 104" className="w-48 shrink-0">
          <path d={`M 20 90 A ${R} ${R} 0 0 1 160 90`} fill="none" stroke="#e8e8ed" strokeWidth="12" strokeLinecap="round" />
          <motion.path
            d={`M 20 90 A ${R} ${R} 0 0 1 160 90`}
            fill="none"
            stroke={color}
            strokeWidth="12"
            strokeLinecap="round"
            strokeDasharray={C}
            initial={{ strokeDashoffset: C }}
            animate={{ strokeDashoffset: C * (1 - frac) }}
            transition={{ duration: 1.2, ease: 'easeOut' }}
          />
          <motion.g initial={{ rotate: -90 }} animate={{ rotate: needle }} transition={{ type: 'spring', stiffness: 60, damping: 12 }} style={{ originX: '90px', originY: '90px' }}>
            <line x1="90" y1="90" x2="90" y2="34" stroke="#1d1d1f" strokeWidth="2.5" strokeLinecap="round" />
          </motion.g>
          <circle cx="90" cy="90" r="5" fill="#1d1d1f" />
          <text x="20" y="104" fill="#6e6e73" fontSize="9" textAnchor="middle" fontFamily="inherit">0%</text>
          <text x="160" y="104" fill="#6e6e73" fontSize="9" textAnchor="middle" fontFamily="inherit">{MAX}%+</text>
        </svg>
        <div className="flex-1 min-w-0 text-center sm:text-left">
          <div className="text-sm font-semibold" style={{ color }}>
            {text}
          </div>
          <div className="font-display text-display-lg font-semibold tabular-nums text-ink">
            {risk.pct_delayed_15.toFixed(1)}%
            <span className="ml-2 text-sm font-normal text-ink-48">delayed 15+ min</span>
          </div>
          <div className="mt-1 text-sm text-ink-48">{ctx}</div>
          <div className="mt-2 flex flex-wrap justify-center sm:justify-start gap-x-4 gap-y-1 text-sm tabular-nums">
            <span className="text-ink-80">avg {risk.avg_dep_delay.toFixed(1)}m</span>
            <span className="text-ink-80">{risk.pct_cancelled.toFixed(1)}% cancelled</span>
            <span className="inline-flex items-center gap-1 text-ink-48">
              <Database className="size-3.5" />
              based on {risk.flights.toLocaleString()} flights
            </span>
          </div>
        </div>
      </div>
      {risk.sql ? (
        <div className="mt-3">
          <button onClick={() => setShowSql((s) => !s)} className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline">
            <Code2 className="size-3.5" />
            {showSql ? 'Hide SQL' : 'View SQL'}
          </button>
          {showSql ? <SqlBlock sql={risk.sql} className="mt-2" /> : null}
        </div>
      ) : null}
    </div>
  )
}
