import type {
  AgentEvent,
  AgentEventType,
  Health,
  HistoryMessage,
  QueryResult,
  WatchEvent,
  WatchEventType,
  WatchedFlight,
} from './types'
import * as mock from './mock'

/** Fixture mode: `?mock=1` in the URL or VITE_MOCK=1 at build/dev time. */
export const MOCK: boolean = (() => {
  const q = new URLSearchParams(window.location.search).get('mock')
  if (q !== null) return q !== '0' && q !== 'false'
  return import.meta.env.VITE_MOCK === '1' || import.meta.env.VITE_MOCK === 'true'
})()

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = ''
    try {
      detail = await res.text()
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail.slice(0, 200)}` : ''}`)
  }
  return (await res.json()) as T
}

const AGENT_TYPES: AgentEventType[] = ['thinking', 'tool_call', 'tool_result', 'delta', 'message', 'error', 'done']
const WATCH_TYPES: WatchEventType[] = ['added', 'removed', 'status_change', 'delay_change', 'gate_change', 'tick']

/**
 * Parse a text/event-stream body. Calls onFrame for every complete frame.
 * Handles \r\n, multi-line data, comments (": ping") and frames split across chunks.
 */
export async function readSSE(
  body: ReadableStream<Uint8Array>,
  onFrame: (event: string, data: string) => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  const flush = (block: string) => {
    let event = 'message'
    const data: string[] = []
    for (const raw of block.split('\n')) {
      const line = raw.endsWith('\r') ? raw.slice(0, -1) : raw
      if (!line || line.startsWith(':')) continue
      const i = line.indexOf(':')
      const field = i === -1 ? line : line.slice(0, i)
      let value = i === -1 ? '' : line.slice(i + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'event') event = value
      else if (field === 'data') data.push(value)
    }
    if (data.length) onFrame(event, data.join('\n'))
  }
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let idx: number
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      flush(buf.slice(0, idx))
      buf = buf.slice(idx + 2)
    }
  }
  buf += decoder.decode()
  if (buf.trim()) flush(buf)
}

function toAgentEvent(event: string, data: string): AgentEvent | null {
  let parsed: unknown
  try {
    parsed = JSON.parse(data)
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== 'object') return null
  const p = parsed as Partial<AgentEvent>
  const type = (p.type ?? event) as AgentEventType
  if (!AGENT_TYPES.includes(type)) return null
  return { type, data: (p.data ?? {}) as Record<string, unknown>, ts: p.ts ?? new Date().toISOString() }
}

export const api = {
  async health(): Promise<Health> {
    if (MOCK) return mock.health()
    return json<Health>(await fetch('/api/health'))
  },

  /** POST /api/chat and stream AgentEvents until the server closes the stream. */
  async chat(
    message: string,
    history: HistoryMessage[] | undefined,
    onEvent: (e: AgentEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    if (MOCK) return mock.chat(message, onEvent, signal)
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ message, history: history ?? [] }),
      signal,
    })
    if (!res.ok || !res.body) {
      const text = await res.text().catch(() => '')
      throw new Error(`chat failed: ${res.status} ${text.slice(0, 200)}`)
    }
    await readSSE(res.body, (event, data) => {
      const e = toAgentEvent(event, data)
      if (e) onEvent(e)
    })
  },

  async ask(question: string): Promise<QueryResult> {
    if (MOCK) return mock.ask(question)
    return json<QueryResult>(
      await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      }),
    )
  },

  async listWatch(): Promise<WatchedFlight[]> {
    if (MOCK) return mock.listWatch()
    return json<WatchedFlight[]>(await fetch('/api/watch'))
  },

  async addWatch(flight_number: string, date?: string): Promise<WatchedFlight> {
    if (MOCK) return mock.addWatch(flight_number, date)
    return json<WatchedFlight>(
      await fetch('/api/watch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(date ? { flight_number, date } : { flight_number }),
      }),
    )
  },

  async removeWatch(id: string): Promise<void> {
    if (MOCK) return mock.removeWatch(id)
    await json<unknown>(await fetch(`/api/watch/${encodeURIComponent(id)}`, { method: 'DELETE' }))
  },

  /** Subscribe to GET /api/events. Returns an unsubscribe function. */
  subscribeEvents(onEvent: (e: WatchEvent) => void, onConn?: (live: boolean) => void): () => void {
    if (MOCK) {
      onConn?.(true)
      return mock.subscribe(onEvent)
    }
    const es = new EventSource('/api/events')
    const handler = (ev: MessageEvent) => {
      onConn?.(true) // any event proves the stream is up, even if onopen was missed
      try {
        const p = JSON.parse(ev.data) as WatchEvent
        if (p && p.flight_id !== undefined) onEvent({ ...p, type: (p.type ?? ev.type) as WatchEventType })
      } catch {
        /* keepalive or junk */
      }
    }
    for (const t of WATCH_TYPES) es.addEventListener(t, handler as EventListener)
    es.onmessage = handler
    es.onopen = () => onConn?.(true)
    es.onerror = () => onConn?.(false) // EventSource auto-reconnects
    return () => es.close()
  },
}
