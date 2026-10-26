import { Code2, Database } from 'lucide-react'
import { useState } from 'react'
import { motion } from 'framer-motion'
import type { DelayRisk } from '../types'
import { SqlBlock } from './SqlBlock'

const LABEL: Record<DelayRisk['label'], { color: string; text: string }> = {
  low: { color: '#34d399', text: 'LOW RISK' },
  medium: { color: '#fbbf24', text: 'MEDIUM RISK' },
  high: { color: '#f87171', text: 'HIGH RISK' },
  unknown: { color: '#94a3b8', text: 'NOT ENOUGH DATA' },
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
    <div className={embedded ? '' : 'glass rounded-2xl p-4 sm:p-5'}>
      <div className="flex flex-col sm:flex-row items-center gap-4 sm:gap-6">
        <svg viewBox="0 0 180 104" className="w-48 shrink-0">
          <defs>
            <linearGradient id="riskgrad" x1="0" x2="1">
              <stop offset="0" stopColor="#34d399" />
              <stop offset="0.5" stopColor="#fbbf24" />
              <stop offset="1" stopColor="#f87171" />
            </linearGradient>
          </defs>
          <path d={`M 20 90 A ${R} ${R} 0 0 1 160 90`} fill="none" stroke="#1c2840" strokeWidth="14" strokeLinecap="round" />
          <motion.path
            d={`M 20 90 A ${R} ${R} 0 0 1 160 90`}
            fill="none"
            stroke="url(#riskgrad)"
            strokeWidth="14"
            strokeLinecap="round"
            strokeDasharray={C}
            initial={{ strokeDashoffset: C }}
            animate={{ strokeDashoffset: C * (1 - frac) }}
            transition={{ duration: 1.2, ease: 'easeOut' }}
          />
          <motion.g initial={{ rotate: -90 }} animate={{ rotate: needle }} transition={{ type: 'spring', stiffness: 60, damping: 12 }} style={{ originX: '90px', originY: '90px' }}>
            <line x1="90" y1="90" x2="90" y2="32" stroke="#fff" strokeWidth="3" strokeLinecap="round" />
          </motion.g>
          <circle cx="90" cy="90" r="6" fill="#fff" />
          <text x="20" y="104" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="JetBrains Mono, monospace">0%</text>
          <text x="160" y="104" fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="JetBrains Mono, monospace">{MAX}%+</text>
        </svg>
        <div className="flex-1 min-w-0 text-center sm:text-left">
          <div className="text-xs font-bold tracking-[0.25em]" style={{ color }}>
            {text}
          </div>
          <div className="font-mono text-4xl font-extrabold text-white">
            {risk.pct_delayed_15.toFixed(1)}%
            <span className="ml-2 text-sm font-normal text-slate-400">delayed 15+ min</span>
          </div>
          <div className="mt-1 text-sm text-slate-400">{ctx}</div>
          <div className="mt-2 flex flex-wrap justify-center sm:justify-start gap-x-4 gap-y-1 text-sm font-mono">
            <span className="text-slate-300">avg {risk.avg_dep_delay.toFixed(1)}m</span>
            <span className="text-slate-300">{risk.pct_cancelled.toFixed(1)}% cancelled</span>
            <span className="inline-flex items-center gap-1 text-sky">
              <Database className="size-3.5" />
              based on {risk.flights.toLocaleString()} flights
            </span>
          </div>
        </div>
      </div>
      {risk.sql ? (
        <div className="mt-3">
          <button onClick={() => setShowSql((s) => !s)} className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-400 hover:text-flap transition">
            <Code2 className="size-3.5" />
            {showSql ? 'Hide SQL' : 'View SQL'}
          </button>
          {showSql ? <SqlBlock sql={risk.sql} className="mt-2" /> : null}
        </div>
      ) : null}
    </div>
  )
}
