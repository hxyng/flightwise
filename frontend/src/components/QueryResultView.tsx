import { AlertTriangle, BarChart3, Code2, Database, MessageSquareText } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ChartSpec, QueryResult } from '../types'
import { Markdown } from './Markdown'
import { SqlBlock } from './SqlBlock'

type Tab = 'answer' | 'chart' | 'sql'

const TIMEY = /hour|month|date|day|year|week|time|period/i

function inferChart(q: QueryResult): ChartSpec | null {
  if (q.chart) return q.chart
  if (q.columns.length < 2 || !q.rows.length) return null
  const yIdx = q.columns.findIndex((_, i) => i > 0 && q.rows.every((r) => typeof r[i] === 'number'))
  if (yIdx < 0) return null
  const x = q.columns[0]
  return { kind: TIMEY.test(x) ? 'line' : 'bar', x, y: q.columns[yIdx] }
}

function fmt(v: unknown): string {
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 })
  if (v == null) return '—'
  return String(v)
}

const axis = { stroke: '#475569', tick: { fill: '#94a3b8', fontSize: 12, fontFamily: 'JetBrains Mono, monospace' } }

function ResultChart({ q, spec }: { q: QueryResult; spec: ChartSpec }) {
  const xi = q.columns.indexOf(spec.x)
  const yi = q.columns.indexOf(spec.y)
  const data = useMemo(
    () => q.rows.map((r) => ({ x: r[xi] as string | number, y: typeof r[yi] === 'number' ? (r[yi] as number) : Number(r[yi]) })),
    [q.rows, xi, yi],
  )
  if (xi < 0 || yi < 0 || !data.length) return <div className="p-6 text-sm text-slate-400">No chartable columns.</div>
  const max = Math.max(...data.map((d) => d.y))
  const min = Math.min(...data.map((d) => d.y))
  const tooltip = (
    <Tooltip
      cursor={{ fill: 'rgba(255,179,0,0.06)', stroke: 'rgba(255,179,0,0.4)' }}
      contentStyle={{ background: '#0c1322', border: '1px solid #22304d', borderRadius: 10, fontFamily: 'JetBrains Mono, monospace' }}
      labelStyle={{ color: '#94a3b8' }}
      itemStyle={{ color: '#ffb300' }}
      formatter={(v) => [fmt(v), spec.y]}
      labelFormatter={(l) => `${spec.x}: ${l}`}
    />
  )
  return (
    <div className="h-64 sm:h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        {spec.kind === 'line' ? (
          <AreaChart data={data} margin={{ top: 16, right: 16, bottom: 4, left: -8 }}>
            <defs>
              <linearGradient id="areafill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ffb300" stopOpacity={0.45} />
                <stop offset="100%" stopColor="#ffb300" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#1c2840" strokeDasharray="3 4" vertical={false} />
            <XAxis dataKey="x" {...axis} />
            <YAxis {...axis} width={48} />
            {tooltip}
            <Area
              type="monotone"
              dataKey="y"
              stroke="#ffb300"
              strokeWidth={3}
              fill="url(#areafill)"
              dot={{ r: 3, fill: '#ffb300', strokeWidth: 0 }}
              activeDot={{ r: 6, fill: '#fff' }}
              animationDuration={1200}
            />
          </AreaChart>
        ) : (
          <BarChart data={data} margin={{ top: 16, right: 16, bottom: 4, left: -8 }}>
            <CartesianGrid stroke="#1c2840" strokeDasharray="3 4" vertical={false} />
            <XAxis dataKey="x" {...axis} />
            <YAxis {...axis} width={48} />
            {tooltip}
            <Bar dataKey="y" radius={[6, 6, 0, 0]} animationDuration={1000}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.y === min ? '#34d399' : d.y === max ? '#f87171' : '#ffb300'} fillOpacity={d.y === min || d.y === max ? 1 : 0.75} />
              ))}
            </Bar>
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}

export function QueryResultView({ q, bare = false }: { q: QueryResult; bare?: boolean }) {
  const spec = inferChart(q)
  const [tab, setTab] = useState<Tab>(spec ? 'chart' : 'answer')
  const tabs: { id: Tab; label: string; icon: typeof BarChart3; show: boolean }[] = [
    { id: 'answer', label: 'Answer', icon: MessageSquareText, show: true },
    { id: 'chart', label: 'Chart', icon: BarChart3, show: !!spec },
    { id: 'sql', label: 'SQL', icon: Code2, show: !!q.sql },
  ]

  return (
    <div className={bare ? '' : 'glass rounded-2xl overflow-hidden'}>
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-3">
        <div className="text-sm text-slate-400 min-w-0">
          <span className="text-slate-500">Q:</span> <span className="text-slate-200">{q.question}</span>
        </div>
        {q.backend ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-sky/40 bg-sky/10 px-2 py-0.5 text-[0.7rem] font-bold uppercase tracking-wider text-sky">
            <Database className="size-3" /> {q.backend}
          </span>
        ) : null}
      </div>

      {q.error ? (
        <div className="m-4 flex items-start gap-2 rounded-xl border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          <AlertTriangle className="size-4 mt-0.5 shrink-0" /> {q.error}
        </div>
      ) : null}

      {q.answer ? (
        <div className="md px-4 pt-2 text-base sm:text-lg leading-relaxed text-slate-100">
          <Markdown text={q.answer} />
        </div>
      ) : null}

      <div className="flex gap-1 px-4 pt-3 border-b border-line/70">
        {tabs
          .filter((t) => t.show)
          .map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`relative inline-flex items-center gap-1.5 px-3 py-2 text-sm font-semibold transition ${tab === t.id ? 'text-flap' : 'text-slate-400 hover:text-slate-200'}`}
            >
              <t.icon className="size-4" />
              {t.label}
              {tab === t.id ? <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-flap" /> : null}
            </button>
          ))}
        <span className="ml-auto self-center text-xs font-mono text-slate-500">{q.rows.length} rows</span>
      </div>

      <div className="p-3 sm:p-4">
        {tab === 'chart' && spec ? <ResultChart q={q} spec={spec} /> : null}
        {tab === 'sql' && q.sql ? <SqlBlock sql={q.sql} /> : null}
        {tab === 'answer' ? (
          q.rows.length ? (
            <div className="scrollbar-thin max-h-72 overflow-auto rounded-xl border border-line">
              <table className="w-full text-sm font-mono">
                <thead className="sticky top-0 bg-ink-800">
                  <tr>
                    {q.columns.map((c) => (
                      <th key={c} className="px-3 py-2 text-left text-[0.7rem] uppercase tracking-wider text-slate-400 whitespace-nowrap">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {q.rows.slice(0, 100).map((r, i) => (
                    <tr key={i} className="border-t border-line/50 odd:bg-white/[0.02]">
                      {r.map((v, j) => (
                        <td key={j} className={`px-3 py-1.5 whitespace-nowrap ${typeof v === 'number' ? 'text-right text-slate-200' : 'text-flap'}`}>
                          {fmt(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-sm text-slate-400">No rows returned.</div>
          )
        ) : null}
      </div>
    </div>
  )
}
