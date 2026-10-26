import type { DelayRisk, FlightOffer, FlightPhase, FlightStatus, QueryResult, WatchedFlight } from '../types'

export function hhmm(isoStr?: string | null): string {
  if (!isoStr) return '--:--'
  const d = new Date(isoStr)
  if (Number.isNaN(d.getTime())) return '--:--'
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
}

export function duration(min: number): string {
  const h = Math.floor(min / 60)
  const m = min % 60
  return h ? `${h}h ${m.toString().padStart(2, '0')}m` : `${m}m`
}

export function money(v: number | null | undefined, cur = 'USD'): string {
  if (v == null) return '—'
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency: cur, maximumFractionDigits: 0 }).format(v)
  } catch {
    return `$${Math.round(v)}`
  }
}

export function phaseLabel(p: FlightPhase): string {
  return p === 'en_route' ? 'EN ROUTE' : p.toUpperCase()
}

/** Tailwind text/bg classes for a flight phase. */
export function phaseTone(p: FlightPhase, delay?: number | null): 'ok' | 'warn' | 'bad' | 'sky' | 'dim' {
  if (p === 'cancelled' || p === 'diverted') return 'bad'
  if (p === 'delayed' || (delay ?? 0) >= 15) return 'warn'
  if (p === 'boarding') return 'sky'
  if (p === 'landed' || p === 'en_route' || p === 'departed') return 'ok'
  if (p === 'unknown') return 'dim'
  return 'ok'
}

export const TONE_TEXT: Record<string, string> = {
  ok: 'text-ok',
  warn: 'text-warn',
  bad: 'text-bad',
  sky: 'text-sky',
  dim: 'text-slate-400',
}
export const TONE_DOT: Record<string, string> = {
  ok: 'bg-ok',
  warn: 'bg-warn',
  bad: 'bg-bad',
  sky: 'bg-sky',
  dim: 'bg-slate-500',
}

// ---- tool_result classification (shape-based, so it tolerates backend variations)

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)

export const isFlightStatus = (v: unknown): v is FlightStatus =>
  isObj(v) && typeof v.flight_number === 'string' && typeof v.origin === 'string' && typeof v.destination === 'string' && typeof v.status === 'string'
export const isOffer = (v: unknown): v is FlightOffer => isObj(v) && Array.isArray(v.flight_numbers) && typeof v.duration_min === 'number'
export const isRisk = (v: unknown): v is DelayRisk => isObj(v) && typeof v.pct_delayed_15 === 'number' && typeof v.flights === 'number'
export const isQuery = (v: unknown): v is QueryResult => isObj(v) && typeof v.question === 'string' && ('sql' in v || 'rows' in v || 'answer' in v)
export const isWatched = (v: unknown): v is WatchedFlight => isObj(v) && typeof v.id === 'string' && typeof v.flight_number === 'string' && typeof v.date === 'string'

export type Classified =
  | { kind: 'status'; status: FlightStatus; risk: DelayRisk | null }
  | { kind: 'risk'; risk: DelayRisk }
  | { kind: 'offers'; offers: FlightOffer[] }
  | { kind: 'query'; query: QueryResult }
  | { kind: 'watched'; flights: WatchedFlight[] }
  | { kind: 'error'; text: string }
  | { kind: 'raw'; value: unknown }

export function classify(result: unknown): Classified {
  if (typeof result === 'string') {
    try {
      return classify(JSON.parse(result))
    } catch {
      return { kind: 'raw', value: result }
    }
  }
  if (Array.isArray(result)) {
    if (result.length && result.every(isOffer)) return { kind: 'offers', offers: result }
    if (result.length && result.every(isWatched)) return { kind: 'watched', flights: result }
    if (result.length === 0) return { kind: 'raw', value: 'No results' }
    if (result.every(isFlightStatus)) return { kind: 'status', status: result[0], risk: null }
    return { kind: 'raw', value: result }
  }
  if (!isObj(result)) return { kind: 'raw', value: result }
  if (isQuery(result)) return { kind: 'query', query: result }
  if (isRisk(result)) return { kind: 'risk', risk: result }
  if (isFlightStatus(result)) return { kind: 'status', status: result, risk: null }
  if (isWatched(result)) return { kind: 'watched', flights: [result] }
  // composite, e.g. track_flight -> {status, risk} / {flight, delay_risk}
  const st = [result.status, result.flight, result.flight_status, result.last_status].find(isFlightStatus)
  const rk = [result.risk, result.delay_risk].find(isRisk) ?? null
  if (st) return { kind: 'status', status: st, risk: rk }
  if (rk) return { kind: 'risk', risk: rk }
  const offs = [result.offers, result.flights, result.results].find((v) => Array.isArray(v) && v.length && v.every(isOffer))
  if (offs) return { kind: 'offers', offers: offs as FlightOffer[] }
  const w = [result.watched, result.watchlist, result.flights].find((v) => Array.isArray(v) && v.every(isWatched))
  if (w) return { kind: 'watched', flights: w as WatchedFlight[] }
  if (typeof result.error === 'string') return { kind: 'error', text: result.error }
  return { kind: 'raw', value: result }
}

const SQL_KW =
  /\b(SELECT|FROM|WHERE|GROUP|BY|ORDER|HAVING|LIMIT|AND|OR|AS|CASE|WHEN|THEN|ELSE|END|COUNT|AVG|SUM|MIN|MAX|ROUND|FLOOR|DESC|ASC|JOIN|ON|IN|NOT|NULL|IS|DISTINCT|WITH|LIKE|BETWEEN)\b/g

/** Escape and wrap SQL keywords for lightweight highlighting. */
export function highlightSql(sql: string): string {
  const esc = sql.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return esc
    .replace(/('[^']*')/g, '<span class="text-emerald-300">$1</span>')
    .replace(SQL_KW, '<span class="text-flap font-semibold">$1</span>')
}
