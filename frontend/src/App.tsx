import { Bot, Database } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, MOCK } from './api'
import { AgentConsole } from './components/AgentConsole'
import { AskData } from './components/AskData'
import { Header } from './components/Header'
import { Toasts, type Toast } from './components/Toasts'
import { Watchlist } from './components/Watchlist'
import type { FlightStatus, Health, WatchEvent, WatchedFlight } from './types'

type Mode = 'agent' | 'data'
const CHANGE_TYPES = new Set(['status_change', 'delay_change', 'gate_change'])

function notify(e: WatchEvent) {
  try {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(`FlightWise · ${e.flight_number}`, { body: e.message, tag: `${e.flight_id}-${e.type}`, icon: '/favicon.svg' })
    }
  } catch {
    /* some browsers throw outside a service worker */
  }
}

export default function App() {
  const [mode, setMode] = useState<Mode>('agent')
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [watch, setWatch] = useState<WatchedFlight[]>([])
  const [feed, setFeed] = useState<WatchEvent[]>([])
  const [toasts, setToasts] = useState<Toast[]>([])
  const [flashes, setFlashes] = useState<Record<string, number>>({})
  const [live, setLive] = useState(false)
  const askedPermission = useRef(false)
  const toastSeq = useRef(0)

  // health, polled so pills recover when the backend comes up
  useEffect(() => {
    let stop = false
    const load = () =>
      api
        .health()
        .then((h) => {
          if (!stop) {
            setHealth(h)
            setHealthError(null)
          }
        })
        .catch((e: Error) => !stop && setHealthError(e.message))
    load()
    const t = setInterval(load, 15000)
    return () => {
      stop = true
      clearInterval(t)
    }
  }, [])

  const upsert = useCallback((w: WatchedFlight) => {
    setWatch((ws) => {
      const i = ws.findIndex((x) => x.id === w.id || x.flight_number === w.flight_number)
      if (i < 0) return [...ws, w]
      const next = [...ws]
      next[i] = { ...ws[i], ...w, last_status: w.last_status ?? ws[i].last_status, risk: w.risk ?? ws[i].risk }
      return next
    })
  }, [])

  const refresh = useCallback(() => {
    api
      .listWatch()
      .then((ws) => setWatch((cur) => ws.map((w) => ({ ...w, last_status: w.last_status ?? cur.find((c) => c.id === w.id)?.last_status ?? null }))))
      .catch(() => {})
  }, [])

  const pushToast = useCallback((event: WatchEvent) => {
    const id = ++toastSeq.current
    setToasts((ts) => [...ts.slice(-3), { id, event }])
    setTimeout(() => setToasts((ts) => ts.filter((t) => t.id !== id)), 6000)
  }, [])

  // watchlist + live events
  useEffect(() => {
    refresh()
    const unsub = api.subscribeEvents((e) => {
      if (e.type === 'removed') {
        setWatch((ws) => ws.filter((w) => w.id !== e.flight_id))
      } else if (e.type === 'added') {
        upsert({ id: e.flight_id, flight_number: e.flight_number, date: new Date().toISOString().slice(0, 10), last_status: e.status ?? null, created_at: e.ts })
        if (!MOCK) refresh()
      } else if (e.status) {
        const st = e.status
        setWatch((ws) => ws.map((w) => (w.id === e.flight_id || w.flight_number === e.flight_number ? { ...w, last_status: st } : w)))
      }
      if (e.type === 'tick') return
      setFeed((f) => [e, ...f].slice(0, 60))
      if (CHANGE_TYPES.has(e.type) || e.type === 'added') {
        pushToast(e)
        if (CHANGE_TYPES.has(e.type)) {
          setFlashes((m) => ({ ...m, [e.flight_id]: (m[e.flight_id] ?? 0) + 1 }))
          notify(e)
        }
      }
    }, setLive)
    return unsub
  }, [refresh, upsert, pushToast])

  const askNotify = () => {
    if (askedPermission.current) return
    askedPermission.current = true
    try {
      if ('Notification' in window && Notification.permission === 'default') void Notification.requestPermission()
    } catch {
      /* ignore */
    }
  }

  const onWatch = useCallback(
    async (fn: string) => {
      askNotify()
      const w = await api.addWatch(fn)
      upsert(w)
    },
    [upsert],
  )

  const onAgentWatched = useCallback(
    (w: WatchedFlight) => {
      askNotify()
      upsert(w)
    },
    [upsert],
  )

  const onRemove = useCallback(async (id: string) => {
    setWatch((ws) => ws.filter((w) => w.id !== id))
    try {
      await api.removeWatch(id)
    } catch {
      refresh()
    }
  }, [refresh])

  const watchedSet = useMemo(() => new Set(watch.map((w) => w.flight_number)), [watch])
  const liveStatus = useMemo(() => {
    const m = new Map<string, FlightStatus>()
    for (const w of watch) if (w.last_status) m.set(w.flight_number, w.last_status)
    return m
  }, [watch])

  return (
    <div className="min-h-dvh bg-parchment">
      <Header health={health} healthError={healthError} mock={MOCK} />
      <Toasts toasts={toasts} onDismiss={(id) => setToasts((ts) => ts.filter((t) => t.id !== id))} />

      <main className="mx-auto grid max-w-[1440px] grid-cols-1 gap-4 px-3 py-4 sm:gap-6 sm:px-6 sm:py-6 lg:grid-cols-[minmax(0,1fr)_360px] xl:grid-cols-[minmax(0,1fr)_400px]">
        <section className="glass rounded-lg flex h-[82dvh] min-h-[32rem] flex-col p-3 sm:p-6 lg:h-[calc(100dvh-7rem)]">
          <div className="glass-chip mb-3 flex items-center gap-1 self-start rounded-full p-1">
            {(
              [
                { id: 'agent', label: 'Agent console', icon: Bot },
                { id: 'data', label: 'Ask the data', icon: Database },
              ] as const
            ).map((t) => (
              <button
                key={t.id}
                onClick={() => setMode(t.id)}
                className={`inline-flex items-center gap-2 rounded-full px-3.5 sm:px-4 py-1.5 text-sm ${
                  mode === t.id ? 'bg-ink font-semibold text-white shadow-soft' : 'text-ink-80 hover:text-ink'
                }`}
              >
                <t.icon className="size-4" />
                {t.label}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1">
            <div className={mode === 'agent' ? 'h-full' : 'hidden'}>
              <AgentConsole watched={watchedSet} live={liveStatus} onWatch={onWatch} onAgentWatched={onAgentWatched} />
            </div>
            <div className={mode === 'data' ? 'h-full' : 'hidden'}>
              <AskData />
            </div>
          </div>
        </section>

        <aside className="tile-dark on-dark p-4 sm:p-6 lg:sticky lg:top-[4.75rem] lg:h-[calc(100dvh-7rem)]">
          <Watchlist flights={watch} feed={feed} flashes={flashes} live={live} onRemove={onRemove} />
        </aside>
      </main>
    </div>
  )
}
