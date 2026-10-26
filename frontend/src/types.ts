// Mirrors backend/flightwise/models.py. Datetimes arrive as ISO-8601 strings.

export type FlightPhase =
  | 'scheduled'
  | 'boarding'
  | 'departed'
  | 'en_route'
  | 'landed'
  | 'delayed'
  | 'cancelled'
  | 'diverted'
  | 'unknown'

export interface FlightStatus {
  flight_number: string
  airline?: string | null
  airline_code?: string | null
  origin: string
  destination: string
  scheduled_departure?: string | null
  estimated_departure?: string | null
  actual_departure?: string | null
  scheduled_arrival?: string | null
  estimated_arrival?: string | null
  actual_arrival?: string | null
  status: FlightPhase
  departure_delay_min?: number | null
  arrival_delay_min?: number | null
  gate?: string | null
  terminal?: string | null
  aircraft?: string | null
  progress?: number | null
  source: string
  updated_at: string
}

export interface FlightOffer {
  id: string
  airline: string
  airline_code?: string | null
  flight_numbers: string[]
  origin: string
  destination: string
  departure: string
  arrival: string
  duration_min: number
  stops: number
  price?: number | null
  currency: string
  source: string
  // added by the agent's search tool
  risk?: DelayRisk | { error: string }
  recommended?: boolean
  why?: string
}

export interface DelayRisk {
  carrier: string
  origin: string
  hour?: number | null
  month?: number | null
  flights: number
  pct_delayed_15: number
  avg_dep_delay: number
  pct_cancelled: number
  label: 'low' | 'medium' | 'high' | 'unknown'
  sql: string
}

export interface ChartSpec {
  kind: 'line' | 'bar'
  x: string
  y: string
}

export interface QueryResult {
  question: string
  sql?: string | null
  columns: string[]
  rows: unknown[][]
  chart?: ChartSpec | null
  answer?: string | null
  backend?: string | null
  error?: string | null
}

export interface WatchedFlight {
  id: string
  flight_number: string
  date: string
  last_status?: FlightStatus | null
  risk?: DelayRisk | null
  created_at: string
}

export type AgentEventType = 'thinking' | 'tool_call' | 'tool_result' | 'delta' | 'message' | 'error' | 'done'

// delta: {text} streamed piece of the final answer, arrives before `message` (full text)
export interface AgentEvent {
  type: AgentEventType
  data: Record<string, unknown>
  ts: string
}

export type WatchEventType = 'added' | 'removed' | 'status_change' | 'delay_change' | 'gate_change' | 'tick'

export interface WatchEvent {
  type: WatchEventType
  flight_id: string
  flight_number: string
  message: string
  status?: FlightStatus | null
  ts: string
}

export interface Health {
  llm: boolean
  model?: string
  db?: string
  status?: string
  search?: string
  [k: string]: unknown
}

/** ollama-format chat message, passed back as history next turn */
export type HistoryMessage = Record<string, unknown>
