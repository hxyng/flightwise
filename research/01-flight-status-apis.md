# Flight status APIs (checked 2026-10-26)

**TL;DR**
1. Pick **AeroDataBox via API.market** (free Basic: 400 units/mo, 1 req/s, 7-day trial) for flight-by-number+date and airport departures; it is the best fit for the two lookups. Fallback: **AirLabs** (single `api_key` query param; `/flight` and `/schedules`), but its free quota is **unknown** (pricing page did not render).
2. **Premise FALSE: AviationStack free is NOT HTTP-only.** Its pricing page lists HTTPS on Free; 100 req/month is still correct. Free excludes flight schedules, future flights, historical. Too thin for a hackathon.
3. Verify exact AeroDataBox header/base URL in the API.market "Endpoints" tab (not fetchable); fields below marked UNVERIFIED are from memory/spec hints.

## Premise check
- AviationStack Free: 100 requests/month (confirmed), HTTPS included (premise false), non-commercial only, no support. Not on free: historical, airline routes, autocomplete, flight schedules, future flight data. Docs moved to docs.apilayer.com (aviationstack.com/documentation 301s there); docs pages did not render in my fetch. Base URL `https://api.aviationstack.com/v1/flights`, auth `access_key` query param (search snippet of official docs). Default limit 100/page. Per-minute rate limit: unknown.
- Pricing: Basic $49.99/mo 10k; Pro $149.99 50k; Business $499.99 250k.

## Candidate summary
| API | Free tier | Fit | Notes |
|---|---|---|---|
| AeroDataBox (API.market/RapidAPI) | Basic free: 400 units/mo, 1 req/s; API.market 7-day trial (source: aerodatabox.com/pricing). Third-party says 600 units; official page wins | Best: number+date, airport FIDS | Tiered units: tier1=1, tier2=2, tier3=6 units/call. Direct plans "coming soon". Can earn credits by feeding ADS-B |
| AirLabs | "Free package" exists; quota/rate limit **unknown** (page used unfilled template placeholders). Errors exist for minute/hour/month limits | Good: `/flight`, `/schedules` have dep/arr times, gate, delay | Key as `api_key` param, simple |
| AviationStack | 100/mo | Weak on free | See above |
| FlightAware AeroAPI | Personal tier: usage-based with up to $5/mo free credit (official pages per search snippet; older "500 queries" figure conflicts), 10 result sets/min, no historical | Great data, but billing/card setup; signup friction | Official docs returned 401/404 to me; verify |
| OpenSky | Free, ADS-B only (positions), no gate/schedule/delay; site returned 403 to my fetch | Not a status API | Anonymous vs OAuth detail: unknown |
| FlightLabs | Not checked (no time/source) | unknown | |

No shutdowns found for these in 2025-2026. Pricing changes: AeroDataBox direct plans announced ("coming soon"), marketplace tiers as above; AviationStack docs moved to apilayer. Anything else: unknown.

## Pick 1: AeroDataBox (API.market)
Signup: apimarket.aerodatabox.com (or rapid.aerodatabox.com for RapidAPI) -> create account -> subscribe to Basic (free) / start 7-day trial -> copy key.
Docs and OpenAPI specs: https://doc.aerodatabox.com/ ; specs at https://aerodatabox.com/docs/openapi-apimarket-v1.json (and `-direct-v1`). I could not fetch the spec (404 on my first try), so the following are UNVERIFIED beyond the paths:
- Auth: RapidAPI = headers `X-RapidAPI-Key` + `X-RapidAPI-Host: aerodatabox.p.rapidapi.com`. API.market header name and base URL: unknown (check Endpoints tab / spec `servers` + `securitySchemes`).
- (a) Flight by number+date: `GET /flights/number/{flightNumber}/{date}` e.g. `/flights/number/AA100/2026-10-26` (path confirmed from doc page; date YYYY-MM-DD, local).
- (b) Departures: `GET /flights/airports/iata/{code}/{fromLocal}/{toLocal}` e.g. `/flights/airports/iata/JFK/2026-10-26T12:00/2026-10-26T20:00` plus query like `direction=Departure`, `withCancelled`, `withCodeshared` (query names UNVERIFIED; window max 12h from memory, verify).
- Response shape (UNVERIFIED, from memory; confirm against spec): array of flights, each with `number`, `status`, `airline{name,iata}`, `departure{airport{iata,name}, scheduledTime{utc,local}, revisedTime{utc,local}, runwayTime{...}, terminal, gate, quality[]}`, `arrival{...same}`, `aircraft{model,reg}`. Departures endpoint wraps as `{ "departures": [...], "arrivals": [...] }`. Delay is not a field: compute revisedTime - scheduledTime.
- Rate limit free: 1 req/s; 400 units/mo (units != requests).

## Pick 2: AirLabs
Signup: airlabs.co -> "Get a FREE package" -> dashboard shows API key. Auth: `?api_key=KEY` query param. Base: `https://airlabs.co/api/v9`.
- (a) `GET /flight?flight_iata=AA6&api_key=KEY` returns ONE flight (closest live/scheduled/landed). No date param. For all flights sharing a number use `/schedules?flight_iata=AA100`.
- (b) `GET /schedules?dep_iata=JFK&api_key=KEY` (also `arr_iata`, `airline_iata`, `limit`, `offset`, `_fields`).
- Free tier quota / rate limit: **unknown** (not shown on fetched pages; errors `minute_limit_exceeded`, `hour_limit_exceeded`, `month_limit_exceeded` exist).
- Trimmed sample (official docs example values, shortened; timestamps omitted):
```json
{"response":[{
 "airline_iata":"BA","flight_iata":"BA6984","flight_number":"6984",
 "dep_iata":"MIA","dep_terminal":"C","dep_gate":"E4",
 "dep_time":"...","dep_estimated":"...","dep_actual":"...",
 "arr_iata":"SFO","arr_terminal":"...","arr_gate":"...","arr_baggage":"...",
 "arr_time":"...","arr_estimated":"...","arr_actual":"...",
 "status":"scheduled","duration":359,"dep_delayed":137,"arr_delayed":137}]}
```
  Times come in local, `_utc` and `_ts` variants. `/flight` additionally returns live position (`lat,lng,alt,speed`), `reg_number`, aircraft fields. Wrapper key `response` is from memory (UNVERIFIED).
- curl: `curl "https://airlabs.co/api/v9/schedules?dep_iata=JFK&limit=20&api_key=$KEY"`

## AviationStack quick ref (if used anyway)
`curl "https://api.aviationstack.com/v1/flights?access_key=$KEY&flight_iata=AA100"`; `dep_iata=JFK` for departures (param name UNVERIFIED in docs, widely used). Response: `data[]` with `flight_date, flight_status, departure{airport,iata,terminal,gate,delay,scheduled,estimated,actual}, arrival{...}, airline{name,iata}, flight{number,iata}` (from memory; a marketplace sample showed camelCase `scheduledTime/estimatedTime/actualTime` instead, so the schema may have changed: unknown). Free tier excludes `flight_date` historical and schedules.

## Not checked / gaps
FlightLabs; OpenSky details; exact AeroDataBox API.market auth and response (spec not fetched); AirLabs free quota; AviationStack per-minute limit; FlightAware official docs (401/404).
