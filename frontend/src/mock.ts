// Fixture mode (?mock=1 / VITE_MOCK=1): a scripted agent stream and a fake watcher
// that evolves flights on wall-clock time. Doubles as the demo backup.
import type {
  AgentEvent,
  DelayRisk,
  FlightOffer,
  FlightPhase,
  FlightStatus,
  Health,
  QueryResult,
  WatchEvent,
  WatchedFlight,
} from './types'

const iso = (d: Date) => d.toISOString()
const minsFromNow = (m: number) => new Date(Date.now() + m * 60_000)
const today = () => new Date().toISOString().slice(0, 10)

function sleep(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(t)
      reject(new DOMException('aborted', 'AbortError'))
    })
  })
}

// ---------------------------------------------------------------- fixtures

const AIRLINES: Record<string, string> = {
  AA: 'American Airlines',
  UA: 'United Airlines',
  WN: 'Southwest Airlines',
  DL: 'Delta Air Lines',
  F9: 'Frontier Airlines',
}

function makeStatus(
  fn: string,
  origin: string,
  destination: string,
  depInMin: number,
  durMin: number,
  extra: Partial<FlightStatus> = {},
): FlightStatus {
  const code = fn.slice(0, 2)
  const dep = minsFromNow(depInMin)
  const arr = new Date(dep.getTime() + durMin * 60_000)
  return {
    flight_number: fn,
    airline: AIRLINES[code] ?? code,
    airline_code: code,
    origin,
    destination,
    scheduled_departure: iso(dep),
    estimated_departure: iso(dep),
    actual_departure: null,
    scheduled_arrival: iso(arr),
    estimated_arrival: iso(arr),
    actual_arrival: null,
    status: 'scheduled',
    departure_delay_min: 0,
    arrival_delay_min: 0,
    gate: 'B12',
    terminal: '1',
    aircraft: 'Airbus A321',
    progress: 0,
    source: 'mock',
    updated_at: iso(new Date()),
    ...extra,
  }
}

const RISK_SQL = `SELECT COUNT(*) AS flights,
       AVG(CASE WHEN DEP_DELAY >= 15 THEN 1 ELSE 0 END) * 100 AS pct_delayed_15,
       AVG(DEP_DELAY) AS avg_dep_delay,
       AVG(CANCELLED) * 100 AS pct_cancelled
FROM FLIGHTS
WHERE OP_CARRIER = 'AA' AND ORIGIN = 'OKC'
  AND FLOOR(CRS_DEP_TIME / 100) = 17
LIMIT 500`

const AA_RISK: DelayRisk = {
  carrier: 'AA',
  origin: 'OKC',
  hour: 17,
  month: null,
  flights: 1842,
  pct_delayed_15: 22.4,
  avg_dep_delay: 14.8,
  pct_cancelled: 1.9,
  label: 'medium',
  sql: RISK_SQL,
}

const UA_RISK: DelayRisk = { ...AA_RISK, carrier: 'UA', hour: 9, flights: 1210, pct_delayed_15: 13.1, avg_dep_delay: 7.2, pct_cancelled: 0.8, label: 'low', sql: RISK_SQL.replace("'AA'", "'UA'").replace('= 17', '= 9') }

const HOURLY: QueryResult = {
  question: "When's the best time to fly out of OKC?",
  sql: `SELECT FLOOR(CRS_DEP_TIME / 100) AS dep_hour,
       COUNT(*) AS flights,
       ROUND(AVG(CASE WHEN DEP_DELAY >= 15 THEN 1 ELSE 0 END) * 100, 1) AS pct_delayed
FROM FLIGHTS
WHERE ORIGIN = 'OKC'
GROUP BY dep_hour
ORDER BY dep_hour
LIMIT 500`,
  columns: ['dep_hour', 'flights', 'pct_delayed'],
  rows: [
    [5, 2140, 6.1], [6, 4890, 7.4], [7, 4410, 9.2], [8, 3980, 11.0], [9, 3720, 12.6],
    [10, 3350, 14.1], [11, 3190, 15.9], [12, 3240, 17.3], [13, 3010, 18.8], [14, 2870, 20.4],
    [15, 3150, 22.1], [16, 3380, 23.7], [17, 3610, 25.9], [18, 3290, 27.2], [19, 2760, 26.5],
    [20, 1880, 24.0], [21, 940, 21.3],
  ],
  chart: { kind: 'line', x: 'dep_hour', y: 'pct_delayed' },
  answer:
    'Fly **early**. Departures from OKC between **5 and 7 AM** are delayed 15+ minutes only **6–9%** of the time. Risk climbs all day and peaks around **6 PM at 27%**, as delays cascade through the network.',
  backend: 'snowflake',
  error: null,
}

const CARRIERS: QueryResult = {
  question: 'Which airline is most reliable?',
  sql: `SELECT OP_CARRIER AS carrier,
       COUNT(*) AS flights,
       ROUND(AVG(CASE WHEN DEP_DELAY >= 15 THEN 1 ELSE 0 END) * 100, 1) AS pct_delayed,
       ROUND(AVG(CANCELLED) * 100, 2) AS pct_cancelled
FROM FLIGHTS
WHERE ORIGIN = 'OKC'
GROUP BY carrier
HAVING COUNT(*) > 1000
ORDER BY pct_delayed
LIMIT 500`,
  columns: ['carrier', 'flights', 'pct_delayed', 'pct_cancelled'],
  rows: [
    ['DL', 6120, 12.8, 0.61], ['UA', 7340, 15.2, 0.92], ['AA', 18210, 17.9, 1.34],
    ['WN', 15880, 19.6, 1.12], ['AS', 1240, 20.3, 0.88], ['F9', 2110, 26.4, 2.05],
  ],
  chart: { kind: 'bar', x: 'carrier', y: 'pct_delayed' },
  answer:
    "Out of OKC, **Delta (DL)** is the most reliable: only **12.8%** of departures leave 15+ minutes late, with 0.6% cancelled. **Frontier (F9)** is the least reliable at **26.4%**.",
  backend: 'snowflake',
  error: null,
}

const MONTHLY: QueryResult = {
  question: 'Which month has the worst delays?',
  sql: `SELECT MONTH AS month,
       ROUND(AVG(CASE WHEN DEP_DELAY >= 15 THEN 1 ELSE 0 END) * 100, 1) AS pct_delayed
FROM FLIGHTS
GROUP BY month
ORDER BY month
LIMIT 500`,
  columns: ['month', 'pct_delayed'],
  rows: [[1, 17.2], [2, 18.9], [3, 17.5], [4, 16.1], [5, 18.4], [6, 24.6], [7, 25.8], [8, 21.9], [9, 13.4], [10, 14.2], [11, 13.9], [12, 20.7]],
  chart: { kind: 'line', x: 'month', y: 'pct_delayed' },
  answer: '**July** is worst (25.8% of flights delayed 15+ min), driven by summer thunderstorms; **September** is the calmest at 13.4%.',
  backend: 'snowflake',
  error: null,
}

function nextFriday(): string {
  const d = new Date()
  const add = ((5 - d.getDay() + 7) % 7) || 7
  d.setDate(d.getDate() + add)
  return d.toISOString().slice(0, 10)
}

function offers(date: string): FlightOffer[] {
  const at = (h: number, m: number) => {
    const d = new Date(`${date}T00:00:00`)
    d.setHours(h, m, 0, 0)
    return d
  }
  const mk = (id: string, code: string, fns: string[], dh: number, dm: number, dur: number, stops: number, price: number): FlightOffer => {
    const dep = at(dh, dm)
    return {
      id,
      airline: AIRLINES[code] ?? code,
      airline_code: code,
      flight_numbers: fns,
      origin: 'OKC',
      destination: 'DEN',
      departure: iso(dep),
      arrival: iso(new Date(dep.getTime() + dur * 60_000)),
      duration_min: dur,
      stops,
      price,
      currency: 'USD',
      source: 'mock',
    }
  }
  return [
    mk('o1', 'UA', ['UA455'], 6, 5, 95, 0, 148),
    mk('o2', 'WN', ['WN1873'], 7, 40, 100, 0, 129),
    mk('o3', 'F9', ['F9612'], 11, 15, 98, 0, 89),
    mk('o4', 'AA', ['AA2210', 'AA1520'], 9, 20, 228, 1, 176),
    mk('o5', 'UA', ['UA1931'], 17, 30, 97, 0, 212),
    mk('o6', 'DL', ['DL1406', 'DL2289'], 13, 5, 265, 1, 241),
  ]
}

// ---------------------------------------------------------------- fake watcher

type Step = { at: number; type: WatchEvent['type']; apply: (s: FlightStatus) => string }
interface Tracked {
  w: WatchedFlight
  t0: number
  steps: Step[]
  lastTick: number
  rate: number // progress per 3s tick
}

const listeners = new Set<(e: WatchEvent) => void>()
const tracked = new Map<string, Tracked>()
let seq = 0
let timer: ReturnType<typeof setInterval> | null = null

function emit(e: Omit<WatchEvent, 'ts'>) {
  const ev: WatchEvent = { ...e, ts: iso(new Date()) }
  for (const l of listeners) l(ev)
}

function setPhase(s: FlightStatus, status: FlightPhase) {
  s.status = status
  s.updated_at = iso(new Date())
}

function scriptFor(fn: string): Step[] {
  if (fn === 'AA100') {
    return [
      { at: 7, type: 'gate_change', apply: (s) => { const old = s.gate; s.gate = 'B7'; return `AA100 gate changed ${old} → B7` } },
      {
        at: 14, type: 'delay_change', apply: (s) => {
          s.departure_delay_min = 18
          s.arrival_delay_min = 12
          s.estimated_departure = iso(new Date(new Date(s.scheduled_departure!).getTime() + 18 * 60_000))
          s.estimated_arrival = iso(new Date(new Date(s.scheduled_arrival!).getTime() + 12 * 60_000))
          setPhase(s, 'delayed')
          return 'AA100 is now delayed 18 min (late inbound aircraft)'
        },
      },
      { at: 24, type: 'status_change', apply: (s) => { setPhase(s, 'boarding'); return 'AA100 is now boarding at gate B7' } },
      {
        at: 36, type: 'status_change', apply: (s) => {
          s.actual_departure = s.estimated_departure
          s.progress = 0.04
          setPhase(s, 'departed')
          return 'AA100 departed OKC, 18 min late'
        },
      },
      { at: 42, type: 'status_change', apply: (s) => { s.progress = 0.12; setPhase(s, 'en_route'); return 'AA100 is en route to DFW, arriving 12 min late' } },
    ]
  }
  if (fn === 'WN1873') {
    return [
      { at: 30, type: 'status_change', apply: (s) => { setPhase(s, 'boarding'); return 'WN1873 is now boarding at gate A4' } },
      { at: 55, type: 'status_change', apply: (s) => { s.actual_departure = s.scheduled_departure; s.progress = 0.03; setPhase(s, 'en_route'); return 'WN1873 departed OKC on time' } },
    ]
  }
  return [
    { at: 20, type: 'status_change', apply: (s) => { setPhase(s, 'boarding'); return `${s.flight_number} is now boarding` } },
    { at: 40, type: 'status_change', apply: (s) => { s.progress = 0.05; setPhase(s, 'en_route'); return `${s.flight_number} departed ${s.origin}` } },
  ]
}

function loop() {
  const now = Date.now()
  for (const t of tracked.values()) {
    const s = t.w.last_status
    if (!s) continue
    const age = (now - t.t0) / 1000
    while (t.steps.length && t.steps[0].at <= age) {
      const step = t.steps.shift()!
      const message = step.apply(s)
      emit({ type: step.type, flight_id: t.w.id, flight_number: s.flight_number, message, status: { ...s } })
    }
    if ((s.status === 'en_route' || s.status === 'departed') && now - t.lastTick > 3000) {
      t.lastTick = now
      const p = Math.min(1, (s.progress ?? 0) + t.rate)
      s.progress = p
      s.updated_at = iso(new Date())
      if (p >= 1) {
        s.actual_arrival = iso(new Date())
        setPhase(s, 'landed')
        s.gate = s.flight_number === 'UA455' ? 'B32' : s.gate
        emit({ type: 'status_change', flight_id: t.w.id, flight_number: s.flight_number, message: `${s.flight_number} landed at ${s.destination}`, status: { ...s } })
      } else {
        emit({ type: 'tick', flight_id: t.w.id, flight_number: s.flight_number, message: '', status: { ...s } })
      }
    }
  }
}

function track(status: FlightStatus, risk: DelayRisk | null, steps: Step[], rate = 0.02): WatchedFlight {
  const w: WatchedFlight = {
    id: `w${++seq}`,
    flight_number: status.flight_number,
    date: today(),
    last_status: status,
    risk,
    created_at: iso(new Date()),
  }
  tracked.set(w.id, { w, t0: Date.now(), steps, lastTick: Date.now(), rate })
  if (!timer) timer = setInterval(loop, 500)
  return w
}

let seeded = false
function seed() {
  if (seeded) return
  seeded = true
  track(
    makeStatus('UA455', 'OKC', 'DEN', -48, 95, {
      status: 'en_route', progress: 0.5, gate: 'C3', aircraft: 'Boeing 737-800',
      actual_departure: iso(minsFromNow(-46)), departure_delay_min: 2,
    }),
    UA_RISK,
    [],
    0.006,
  )
  track(makeStatus('WN1873', 'OKC', 'MDW', 22, 110, { gate: 'A4', aircraft: 'Boeing 737 MAX 8' }), { ...AA_RISK, carrier: 'WN', label: 'low', pct_delayed_15: 14.6, flights: 2290 }, scriptFor('WN1873'))
}

function aa100(): FlightStatus {
  return makeStatus('AA100', 'OKC', 'DFW', 26, 62, { gate: 'B12', terminal: '1', aircraft: 'Airbus A321neo' })
}

// ---------------------------------------------------------------- API surface

export async function health(): Promise<Health> {
  await sleep(250)
  return { llm: true, model: 'gemma4:12b', db: 'snowflake', status: 'mock', search: 'mock', mock: true }
}

export async function listWatch(): Promise<WatchedFlight[]> {
  seed()
  await sleep(200)
  return [...tracked.values()].map((t) => structuredClone(t.w))
}

export async function addWatch(flight_number: string, _date?: string): Promise<WatchedFlight> {
  const fn = flight_number.replace(/\s+/g, '').toUpperCase()
  const existing = [...tracked.values()].find((t) => t.w.flight_number === fn)
  if (existing) return structuredClone(existing.w)
  const s = fn === 'AA100' ? aa100() : makeStatus(fn, 'OKC', 'DEN', 40, 95, { gate: 'C9' })
  const w = track(s, fn === 'AA100' ? AA_RISK : null, scriptFor(fn))
  await sleep(150)
  emit({ type: 'added', flight_id: w.id, flight_number: fn, message: `Now watching ${fn}`, status: { ...s } })
  return structuredClone(w)
}

export async function removeWatch(id: string): Promise<void> {
  const t = tracked.get(id)
  tracked.delete(id)
  if (t) emit({ type: 'removed', flight_id: id, flight_number: t.w.flight_number, message: `Stopped watching ${t.w.flight_number}` })
}

export function subscribe(cb: (e: WatchEvent) => void): () => void {
  seed()
  listeners.add(cb)
  return () => listeners.delete(cb)
}

export async function ask(question: string): Promise<QueryResult> {
  await sleep(1400)
  const q = question.toLowerCase()
  const base = /hour|time|when|morning|evening/.test(q) ? HOURLY : /month|season|summer|winter/.test(q) ? MONTHLY : CARRIERS
  return { ...base, question }
}

type Script = Array<{ wait: number; type: AgentEvent['type']; data: Record<string, unknown> | (() => Promise<Record<string, unknown>>) }>

function scriptForChat(message: string): Script {
  const m = message.toLowerCase()
  if (/track|status|keep me posted|aa\s?100/.test(m)) {
    return [
      { wait: 1800, type: 'thinking', data: { text: 'The user wants live status for AA100 plus ongoing updates. Call track_flight, then watch_flight so the watcher pushes changes.' } },
      { wait: 600, type: 'tool_call', data: { name: 'track_flight', arguments: { flight_number: 'AA100' } } },
      { wait: 1500, type: 'tool_result', data: { name: 'track_flight', result: { status: aa100(), risk: AA_RISK } } },
      { wait: 500, type: 'tool_call', data: { name: 'watch_flight', arguments: { flight_number: 'AA100' } } },
      { wait: 700, type: 'tool_result', data: async () => ({ name: 'watch_flight', result: await addWatch('AA100') }) },
      {
        wait: 400, type: 'message', data: {
          text: "**AA100** (OKC → DFW) is **on schedule**, departing from gate **B12** in about 26 minutes on an Airbus A321neo.\n\nHistorically, American's 5 PM departures from OKC leave **15+ min late 22% of the time** (1,842 flights), so the risk is **medium**.\n\nI've added it to your **watchlist** and will ping you on any gate, delay, or status change.",
        },
      },
    ]
  }
  if (/find|search|flight .*→|okc.*den|book|cheap/.test(m)) {
    const date = nextFriday()
    return [
      { wait: 1800, type: 'thinking', data: { text: `Find flights OKC → DEN for Friday ${date}. Call search_flights, then weigh price against delay history.` } },
      { wait: 600, type: 'tool_call', data: { name: 'search_flights', arguments: { origin: 'OKC', destination: 'DEN', date } } },
      { wait: 1700, type: 'tool_result', data: { name: 'search_flights', result: offers(date) } },
      { wait: 500, type: 'tool_call', data: { name: 'query_delay_history', arguments: { question: 'On-time rate OKC to DEN by carrier' } } },
      { wait: 1400, type: 'tool_result', data: { name: 'query_delay_history', result: { ...CARRIERS, question: 'On-time rate from OKC by carrier' } } },
      {
        wait: 400, type: 'message', data: {
          text: `I found **6 flights** OKC → DEN on Friday.\n\n- **Cheapest:** Frontier F9612 at **$89**, nonstop, but F9 runs late 26% of the time.\n- **Best balance:** Southwest WN1873 at **$129**, nonstop, 7:40 AM. Morning departures have the lowest delay risk.\n- **Most reliable:** United UA455 at **$148**, 6:05 AM, nonstop.\n\nWant me to watch one of these?`,
        },
      },
    ]
  }
  if (/best time|when|hour/.test(m)) {
    return [
      { wait: 1800, type: 'thinking', data: { text: 'This is a historical question. Use query_delay_history: delay rate by scheduled departure hour at OKC.' } },
      { wait: 600, type: 'tool_call', data: { name: 'query_delay_history', arguments: { question: 'Percent of OKC departures delayed 15+ minutes by hour of day' } } },
      { wait: 1900, type: 'tool_result', data: { name: 'query_delay_history', result: HOURLY } },
      { wait: 2200, type: 'message', data: { text: `**Book the first flight out.** Across **${HOURLY.rows.reduce((a, r) => a + (r[1] as number), 0).toLocaleString()} OKC departures**, the 5–7 AM bank is delayed only **6–9%** of the time, versus **27% at 6 PM**. Delays snowball through the day.` } },
    ]
  }
  if (/airline|reliable|carrier|on.?time/.test(m)) {
    return [
      { wait: 1800, type: 'thinking', data: { text: 'Compare carriers by share of departures delayed 15+ minutes. Use query_delay_history.' } },
      { wait: 600, type: 'tool_call', data: { name: 'query_delay_history', arguments: { question: 'Which airline has the lowest delay rate out of OKC?' } } },
      { wait: 1900, type: 'tool_result', data: { name: 'query_delay_history', result: CARRIERS } },
      { wait: 2200, type: 'message', data: { text: CARRIERS.answer! + '\n\nAmerican carries the most OKC traffic and sits in the middle at 17.9%.' } },
    ]
  }
  return [
    { wait: 1800, type: 'thinking', data: { text: 'No tool needed. Explain what I can do.' } },
    {
      wait: 500, type: 'message', data: {
        text: "I'm **FlightWise**, a flight agent running on a local open-weight model. I can:\n\n- **Track** a flight live and watch it for changes\n- **Search** flights between airports\n- Answer questions about **delay history** from millions of BTS flight records in Snowflake\n\nTry: *Track AA100 and keep me posted*.",
      },
    },
  ]
}

export async function chat(message: string, onEvent: (e: AgentEvent) => void, signal?: AbortSignal): Promise<void> {
  const script = scriptForChat(message)
  let finalText = ''
  for (const step of script) {
    await sleep(step.wait, signal)
    const data = typeof step.data === 'function' ? await step.data() : step.data
    if (step.type === 'message') {
      finalText = String(data.text ?? '')
      // stream the answer as deltas first, like the real backend, then the full message
      const pieces = finalText.match(/\S+\s*/g) ?? [finalText]
      for (let i = 0; i < pieces.length; i += 2) {
        onEvent({ type: 'delta', data: { text: pieces.slice(i, i + 2).join('') }, ts: iso(new Date()) })
        await sleep(45, signal)
      }
    }
    onEvent({ type: step.type, data, ts: iso(new Date()) })
  }
  await sleep(150, signal)
  onEvent({
    type: 'done',
    data: { history: [{ role: 'user', content: message }, { role: 'assistant', content: finalText }] },
    ts: iso(new Date()),
  })
}
