"""Shared data contracts. Every module and the frontend speak these shapes.

Change this file only through the orchestrator: all five modules depend on it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def now() -> datetime:
    return datetime.now(timezone.utc)


FlightPhase = Literal[
    "scheduled", "boarding", "departed", "en_route", "landed",
    "delayed", "cancelled", "diverted", "unknown",
]


class FlightStatus(BaseModel):
    flight_number: str                      # normalized IATA, e.g. "AA100"
    airline: str | None = None              # "American Airlines"
    airline_code: str | None = None         # "AA"
    origin: str                             # IATA airport, e.g. "OKC"
    destination: str
    scheduled_departure: datetime | None = None
    estimated_departure: datetime | None = None
    actual_departure: datetime | None = None
    scheduled_arrival: datetime | None = None
    estimated_arrival: datetime | None = None
    actual_arrival: datetime | None = None
    status: FlightPhase = "unknown"
    departure_delay_min: int | None = None
    arrival_delay_min: int | None = None
    gate: str | None = None
    terminal: str | None = None
    aircraft: str | None = None
    progress: float | None = None           # 0..1 of the trip completed, for the UI
    source: str = "mock"                    # "aerodatabox" | "mock"
    updated_at: datetime = Field(default_factory=now)


class FlightOffer(BaseModel):
    id: str
    airline: str
    airline_code: str | None = None
    flight_numbers: list[str]               # one per segment
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    duration_min: int
    stops: int = 0
    price: float | None = None
    currency: str = "USD"
    source: str = "mock"                    # "serpapi" | "mock"


class DelayRisk(BaseModel):
    """Historical delay odds for carrier + origin + departure hour, from BTS data."""
    carrier: str
    origin: str
    hour: int | None = None
    month: int | None = None
    flights: int                            # sample size
    pct_delayed_15: float                   # 0..100, departures delayed >= 15 min
    avg_dep_delay: float                    # minutes
    pct_cancelled: float                    # 0..100
    label: Literal["low", "medium", "high", "unknown"]
    sql: str                                # the query that produced it (shown in UI)


class ChartSpec(BaseModel):
    kind: Literal["line", "bar"]
    x: str
    y: str


class QueryResult(BaseModel):
    question: str
    sql: str | None = None
    columns: list[str] = []
    rows: list[list[Any]] = []
    chart: ChartSpec | None = None
    answer: str | None = None
    backend: str | None = None              # "snowflake" | "duckdb"
    error: str | None = None


class WatchedFlight(BaseModel):
    id: str
    flight_number: str
    date: str                               # YYYY-MM-DD
    last_status: FlightStatus | None = None
    risk: DelayRisk | None = None
    created_at: datetime = Field(default_factory=now)


class AgentEvent(BaseModel):
    """One step of the agent, streamed to the UI over SSE (event name = type)."""
    type: Literal["thinking", "tool_call", "tool_result", "message", "error", "done"]
    data: dict[str, Any] = {}
    # thinking:    {"text"}
    # tool_call:   {"name", "arguments"}
    # tool_result: {"name", "result"}   result = JSON-able payload, e.g. FlightStatus dict
    # message:     {"text"}             final assistant answer (markdown)
    # error:       {"text"}
    # done:        {"history": [...]}   ollama-format messages to send back next turn
    ts: datetime = Field(default_factory=now)


class WatchEvent(BaseModel):
    """Pushed by the watcher over /api/events when a tracked flight changes."""
    type: Literal["added", "removed", "status_change", "delay_change", "gate_change", "tick"]
    flight_id: str
    flight_number: str
    message: str                            # human sentence, e.g. "AA100 is now delayed 25 min"
    status: FlightStatus | None = None
    ts: datetime = Field(default_factory=now)
