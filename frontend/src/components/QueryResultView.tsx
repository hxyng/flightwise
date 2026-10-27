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

const axis = { stroke: '#d2d2d7', tick: { fill: '#6e6e73', fontSize: 12 } }
const SERIES = '#1d1d1f'

function ResultChart({ q, spec }: { q: QueryResult; spec: ChartSpec }) {
  const xi = q.columns.indexOf(spec.x)
  const yi = q.columns.indexOf(spec.y)
  const data = useMemo(
    () => q.rows.map((r) => ({ x: r[xi] as string | number, y: typeof r[yi] === 'number' ? (r[yi] as number) : Number(r[yi]) })),
    [q.rows, xi, yi],
  )
  if (xi < 0 || yi < 0 || !data.length) return <div className="p-6 text-sm text-ink-48">No chartable columns.</div>
  const max = Math.max(...data.map((d) => d.y))
  const min = Math.min(...data.map((d) => d.y))
  const tooltip = (
    <Tooltip
      cursor={{ fill: 'rgba(0,0,0,0.04)', stroke: 'rgba(0,0,0,0.2)' }}
      contentStyle={{ background: '#fff', border: '1px solid #e0e0e0', borderRadius: 11, fontSize: 14 }}
      labelStyle={{ color: '#6e6e73' }}
      itemStyle={{ color: '#1d1d1f', fontWeight: 600 }}
      formatter={(v) => [fmt(v), spec.y]}
      labelFormatter={(l) => `${spec.x}: ${l}`}
    />
  )
  return (
    <div className="h-64 sm:h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        {spec.kind === 'line' ? (
          <AreaChart data={data} margin={{ top: 16, right: 16, bottom: 4, left: -8 }}>
            <CartesianGrid stroke="#f0f0f0" vertical={false} />
            <XAxis dataKey="x" {...axis} />
            <YAxis {...axis} width={48} />
            {tooltip}
            <Area
              type="monotone"
              dataKey="y"
              stroke={SERIES}
              strokeWidth={2.5}
              fill={SERIES}
              fillOpacity={0.06}
              dot={{ r: 3, fill: SERIES, strokeWidth: 0 }}
              activeDot={{ r: 5, fill: '#fff', stroke: SERIES, strokeWidth: 2 }}
              animationDuration={1200}
            />
          </AreaChart>
        ) : (
          <BarChart data={data} margin={{ top: 16, right: 16, bottom: 4, left: -8 }}>
            <CartesianGrid stroke="#f0f0f0" vertical={false} />
            <XAxis dataKey="x" {...axis} />
            <YAxis {...axis} width={48} />
            {tooltip}
            <Bar dataKey="y" radius={[5, 5, 0, 0]} animationDuration={1000}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.y === min ? '#248a3d' : d.y === max ? '#d70015' : SERIES} fillOpacity={d.y === min || d.y === max ? 1 : 0.8} />
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
    <div className={bare ? '' : 'card overflow-hidden'}>
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 sm:px-6 pt-4">
        <div className="text-sm text-ink-48 min-w-0">
          <span>Q:</span> <span className="text-ink-80">{q.question}</span>
        </div>
        {q.backend ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-parchment px-2.5 py-0.5 text-xs text-ink-80">
            <Database className="size-3" /> {q.backend}
          </span>
        ) : null}
      </div>

      {q.error ? (
        <div className="mx-4 sm:mx-6 mt-3 flex items-start gap-2 rounded-md bg-bad/8 p-3 text-sm text-bad">
          <AlertTriangle className="size-4 mt-0.5 shrink-0" /> {q.error}
        </div>
      ) : null}

      {q.answer ? (
        <div className="md px-4 sm:px-6 pt-2 text-base text-ink">
          <Markdown text={q.answer} />
        </div>
      ) : null}

      <div className="flex gap-1 px-4 sm:px-6 pt-3 border-b border-divider">
        {tabs
          .filter((t) => t.show)
          .map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`relative inline-flex items-center gap-1.5 px-2.5 sm:px-3 py-2 text-sm ${tab === t.id ? 'font-semibold text-ink' : 'text-ink-48 hover:text-ink'}`}
            >
              <t.icon className="size-4" />
              {t.label}
              {tab === t.id ? <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-ink" /> : null}
            </button>
          ))}
        <span className="ml-auto self-center whitespace-nowrap pl-2 text-xs tabular-nums text-ink-48">{q.rows.length} rows</span>
      </div>

      <div className="p-3 sm:p-6 sm:pt-4">
        {tab === 'chart' && spec ? <ResultChart q={q} spec={spec} /> : null}
        {tab === 'sql' && q.sql ? <SqlBlock sql={q.sql} /> : null}
        {tab === 'answer' ? (
          q.rows.length ? (
            <div className="scrollbar-thin max-h-72 overflow-auto rounded-sm border border-hairline">
              <table className="w-full text-sm tabular-nums">
                <thead className="sticky top-0 bg-parchment">
                  <tr>
                    {q.columns.map((c) => (
                      <th key={c} className="px-3 py-2 text-left text-xs font-semibold text-ink-48 whitespace-nowrap">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {q.rows.slice(0, 100).map((r, i) => (
                    <tr key={i} className="border-t border-divider">
                      {r.map((v, j) => (
                        <td key={j} className={`px-3 py-1.5 whitespace-nowrap ${typeof v === 'number' ? 'text-right text-ink-80' : 'text-ink'}`}>
                          {fmt(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-sm text-ink-48">No rows returned.</div>
          )
        ) : null}
      </div>
    </div>
  )
}
