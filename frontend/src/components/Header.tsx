import { Cpu, Database, Plane, Radio, Search, WifiOff } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Health } from '../types'

function Pill({ ok, icon: Icon, label, value, title }: { ok: boolean | null; icon: typeof Cpu; label: string; value: string; title?: string }) {
  const dot = ok === null ? 'bg-bad' : ok ? 'bg-ok' : 'bg-warn'
  return (
    <span title={title} className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-xs whitespace-nowrap text-white ring-1 ring-inset ring-white/10">
      <span className={`size-1.5 rounded-full ${dot}`} />
      <Icon className="size-3.5 text-body-muted" />
      <span className="hidden md:inline text-body-muted">{label}</span>
      <span>{value}</span>
    </span>
  )
}

function Clock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  return (
    <div className="hidden 2xl:flex items-baseline gap-2 text-xs tabular-nums">
      <span className="text-body-muted">{now.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })}</span>
      <span className="text-white">{now.toLocaleTimeString([], { hour12: false })}</span>
    </div>
  )
}

export function Header({ health, healthError, mock }: { health: Health | null; healthError: string | null; mock: boolean }) {
  const live = (v?: string) => !!v && v !== 'mock'
  return (
    <header className="on-dark sticky top-0 z-40 border-b border-white/10 bg-[rgb(22_22_23/0.86)] backdrop-blur-xl backdrop-saturate-[1.8]">
      <div className="mx-auto flex min-h-11 max-w-[1440px] flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-1.5 sm:px-6">
        <div className="flex items-center gap-2">
          <Plane className="size-4 -rotate-45 text-white" strokeWidth={2.25} />
          <span className="text-base font-semibold text-white">FlightWise</span>
          <span className="hidden sm:inline text-xs text-body-muted">Autonomous flight agent</span>
        </div>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-1.5 sm:gap-2">
          {mock ? <Pill ok={false} icon={Radio} label="mode" value="REPLAY" title="Fixture mode: scripted agent + fake watcher (?mock=1)" /> : null}
          {healthError ? (
            <Pill ok={null} icon={WifiOff} label="api" value="offline" title={healthError} />
          ) : health ? (
            <>
              <Pill
                ok={!!health.llm}
                icon={Cpu}
                label="model"
                value={health.model ? String(health.model) : health.llm ? 'online' : 'offline'}
                title={health.llm ? 'Local open-weight model reachable' : 'LLM not reachable'}
              />
              <Pill
                ok={health.db === 'snowflake'}
                icon={Database}
                label="data"
                value={health.db === 'snowflake' ? 'Snowflake' : health.db === 'duckdb' ? 'DuckDB' : String(health.db ?? '?')}
              />
              <Pill ok={live(health.status)} icon={Radio} label="status" value={live(health.status) ? 'live' : 'mock'} title={`status provider: ${health.status ?? '?'}`} />
              <Pill ok={live(health.search)} icon={Search} label="search" value={live(health.search) ? 'live' : 'mock'} title={`search provider: ${health.search ?? '?'}`} />
            </>
          ) : (
            <span className="text-xs text-body-muted">Checking systems…</span>
          )}
        </div>
        <Clock />
      </div>
    </header>
  )
}
