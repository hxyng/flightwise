import { Cpu, Database, Plane, Radio, Search, WifiOff } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Health } from '../types'

function Pill({ ok, icon: Icon, label, value, title }: { ok: boolean | null; icon: typeof Cpu; label: string; value: string; title?: string }) {
  const cls = ok === null ? 'border-bad/40 bg-bad/10 text-bad' : ok ? 'border-ok/40 bg-ok/10 text-ok' : 'border-warn/40 bg-warn/10 text-warn'
  return (
    <span title={title} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold whitespace-nowrap ${cls}`}>
      <Icon className="size-3.5" />
      <span className="hidden md:inline font-medium text-slate-400">{label}</span>
      <span className="font-mono">{value}</span>
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
    <div className="hidden 2xl:block text-right font-mono leading-tight">
      <div className="text-xl font-bold text-flap">{now.toLocaleTimeString([], { hour12: false })}</div>
      <div className="text-[0.65rem] tracking-[0.2em] text-slate-500">
        {now.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }).toUpperCase()}
      </div>
    </div>
  )
}

export function Header({ health, healthError, mock }: { health: Health | null; healthError: string | null; mock: boolean }) {
  const live = (v?: string) => !!v && v !== 'mock'
  return (
    <header className="sticky top-0 z-40 border-b border-line/70 bg-ink-950/80 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
          <div className="relative grid size-10 place-items-center rounded-xl bg-gradient-to-br from-flap to-amber-600 shadow-lg shadow-flap/30">
            <Plane className="size-5 -rotate-45 text-ink-950" strokeWidth={2.5} />
          </div>
          <div className="leading-none">
            <div className="text-2xl font-extrabold tracking-tight text-white">
              Flight<span className="text-flap">Wise</span>
            </div>
            <div className="mt-1 font-mono text-[0.6rem] tracking-[0.3em] text-slate-500">AUTONOMOUS FLIGHT AGENT</div>
          </div>
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
            <span className="text-xs text-slate-500">checking systems…</span>
          )}
        </div>
        <Clock />
      </div>
    </header>
  )
}
