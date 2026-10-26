# FlightWise build contracts

FlightWise is an autonomous flight agent. A local open model (Ollama, `gemma4:12b`) picks tools
to search flights, track live status, watch flights in the background and push updates, and
asks a Snowflake table of US BTS on-time history (text-to-SQL) to predict delay risk.
It targets Hacklahoma's "Best Open-Source AI Project (with Snowflake)" prizes: no paid AI API.

Shared types: `backend/flightwise/models.py`. Settings: `backend/flightwise/config.py`.
LLM client: `backend/flightwise/llm.py` (`chat`, `chat_json`, `health`, `warm`).
These three files are owned by the orchestrator: don't edit them. If one is wrong, say so in your report.

Run Python from `backend/` (`cd backend && python -m pytest tests`); the package is `flightwise`.
Python 3.11. Deps in `requirements.txt` (already installed). Offline-first: every external
dependency has a fallback so the demo never dies on bad Wi-Fi.

## Module interfaces (owner in brackets)

### [B1] `flightwise/providers/status.py`, `search.py`, `mock.py`
```python
async def get_flight_status(flight_number: str, date: str | None = None) -> FlightStatus
async def get_departures(airport: str, limit: int = 20) -> list[FlightStatus]
async def search_flights(origin: str, destination: str, date: str, adults: int = 1) -> list[FlightOffer]
def provider_names() -> dict  # {"status": "aerodatabox"|"mock", "search": "serpapi"|"mock"}
```
Real APIs when keys are set (AeroDataBox via API.market, SerpApi google_flights); otherwise, or on
any HTTP error/timeout (8s), mock. Mock status must be deterministic per (flight_number, date) and
evolve with wall-clock time so the watcher sees changes during a 2-minute demo:
scheduled → boarding → departed/en_route → landed, with some flights picking up a delay or gate change.
Normalize flight numbers ("aa 100" → "AA100").

### [B2] `flightwise/data/db.py`, `guard.py`, `nl2sql.py`, `scripts/fetch_bts.py`, `scripts/load_snowflake.py`
```python
def run_query(sql: str) -> pandas.DataFrame       # Snowflake if configured, else DuckDB over data/flights.parquet
def get_schema() -> str                            # compact column list + meaning, for the prompt
def backend_name() -> str                          # "snowflake" | "duckdb"
def check_sql(sql: str) -> str                     # guard: single SELECT only, add LIMIT 500; raises GuardError
def ask(question: str, explain: bool = True) -> QueryResult   # NL -> SQL -> guard -> run (1 retry with error) -> chart -> explain
def delay_risk(carrier: str, origin: str, hour: int | None = None, month: int | None = None) -> DelayRisk
```
Table `FLIGHTS` (BTS columns, see `research/05-bts-dataset.md`). Same SQL must run on both Snowflake
and DuckDB, so stick to the common subset.

### [B3] `flightwise/agent.py`
```python
TOOLS: list[dict]                                  # ollama tool schemas
async def run_agent(message: str, history: list[dict] | None = None) -> AsyncIterator[AgentEvent]
```
Tools: `search_flights`, `track_flight` (status + delay_risk for its carrier/origin/hour),
`query_delay_history` (nl2sql.ask), `watch_flight` (watcher.add), `list_watched`.
Imports `watcher` lazily from `flightwise.watcher` (`from .watcher import watcher`).

### [B4] `flightwise/watcher.py`, `flightwise/api.py`, `flightwise/demo_cache.py`
```python
class Watcher:
    async def add(self, flight_number: str, date: str | None = None) -> WatchedFlight
    async def remove(self, flight_id: str) -> bool
    def list(self) -> list[WatchedFlight]
    def subscribe(self) -> asyncio.Queue[WatchEvent]; def unsubscribe(self, q) -> None
    async def run(self) -> None                    # poll every config.WATCH_INTERVAL_S, diff, publish
watcher = Watcher()
```
HTTP API (FastAPI app at `flightwise.api:app`, run `uvicorn flightwise.api:app --port 8000`):
| method | path | body / query | returns |
|---|---|---|---|
| POST | /api/chat | `{message, history?}` | SSE stream; event name = AgentEvent.type, data = AgentEvent JSON |
| POST | /api/ask | `{question}` | QueryResult |
| GET | /api/flights/search | origin, destination, date | FlightOffer[] |
| GET | /api/flights/status/{flight_number} | date? | FlightStatus |
| GET | /api/risk | carrier, origin, hour?, month? | DelayRisk |
| GET | /api/watch | | WatchedFlight[] |
| POST | /api/watch | `{flight_number, date?}` | WatchedFlight |
| DELETE | /api/watch/{id} | | `{ok}` |
| GET | /api/events | | SSE stream of WatchEvent (event name = type), keepalive pings |
| GET | /api/health | | `{llm: bool, model, db: "snowflake"/"duckdb", status: ..., search: ...}` |
CORS open for `http://localhost:5173`. Serve `frontend/dist` at `/` when it exists.

### [B5] `frontend/` (Vite + React + TypeScript + Tailwind)
Talks only to the HTTP API above via the Vite proxy `/api → http://localhost:8000`.
TS types mirror `models.py` in `frontend/src/types.ts`.

## Coordination
- Own only your files. Shared board: `BOARD.md` at repo root. Add one line when you start and mark it DONE.
- Code against the contracts. If a dependency isn't built yet, fake it in your tests (monkeypatch).
- Don't run git commands. The orchestrator commits.
