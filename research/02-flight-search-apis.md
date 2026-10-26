# Flight search APIs for a 4-hour hackathon (researched 2026-10-26)

**TL;DR**
1. PRIMARY FINDING: the premise is FALSE. Amadeus Self-Service (and its free test env) was shut down 2026-07-17; registrations were paused earlier. Do not plan on it.
2. Pick #1 for realistic prices/schedules: **SerpApi `google_flights`** (free 250 searches/mo, key at signup). Pick #2 for a bookable-flow demo with a free sandbox: **Duffel test mode** (instant token, but data is mostly fake "Duffel Airways").
3. Kiwi Tequila: appears partner-only (vendor claims, not official). AeroDataBox: schedules only, no prices, free quota unknown.

## Status of each candidate
| Candidate | Status (2026-10-26) | Evidence |
|---|---|---|
| Amadeus Self-Service | **Decommissioned.** Keys disabled and portal gone 2026-07-17. Enterprise APIs remain, access by approval request only. | PhocusWire reports (search snippets; direct fetch of the article returned 403, so not verified firsthand); ignav.com page says "decommissioned" (vendor, competitor) |
| Duffel (test mode) | Open. Free sandbox token, no approval mentioned. | duffel.com/docs/api/overview/test-mode (fetched) |
| SerpApi Google Flights | Open. Free plan 250 searches/mo, 50/hr. | serpapi.com/pricing (fetched); July 2025 changelog |
| Kiwi Tequila | Likely closed to self-serve since 2024; partner application via tequila.kiwi.com. **Unverified**: only competitor/vendor pages say so; tequila.kiwi.com fetch returned only a title. Treat as unavailable. | ignav.com, vervotech (vendors) |
| Skyscanner/RapidAPI wrappers | **Unknown.** Not researched in depth; no official source reviewed. | - |
| AeroDataBox | Exists on RapidAPI and API.Market. Free-tier quota: **unknown** (doc.api.market fetch failed, 521). Airport schedules/FIDS, no prices; origin-to-destination search not confirmed (likely per-airport departures you filter yourself). | search snippets only |
| Ignav (extra) | Vendor claims 1,000 free requests, then $2/1k. Not verified; endpoint shape **unknown**. Fallback only if the top 2 fail. | ignav.com (competitor-written) |

## Pick 1: SerpApi Google Flights

Realism: real Google Flights prices and schedules. Caveat: scraped data; one search = one credit; no booking.

**Signup:** serpapi.com/users/sign_up, verify email, copy key from the dashboard. Phone verification: **unknown** (docs do not say). Google Flights on the free plan: not explicitly confirmed by the pricing page; one review says all engines work on free. Verify with one test call.

**Auth:** `api_key` query param. **Base URL:** `https://serpapi.com/search`

**Quota:** Free 250 successful searches/month, 50/hour throughput. Cached/failed searches are not counted. (An older cached pricing snapshot showed 100/mo; the current fetch showed 250.) Cache repeated demo queries in your app.

**One-way search** (`type=2` is one way; 1 = round trip, 3 = multi-city):
```
curl -G https://serpapi.com/search \
  -d engine=google_flights \
  -d departure_id=SFO -d arrival_id=JFK \
  -d outbound_date=2026-11-15 \
  -d type=2 -d adults=1 -d currency=USD -d hl=en \
  -d api_key=$SERPAPI_KEY
```
Params: `engine` (required), `api_key` (required), `departure_id`/`arrival_id` (IATA codes; needed in practice), `outbound_date` (required when type is 1 or 2), `type` (default 1), `adults` (default 1), `currency` (default USD). `return_date` only for round trip. I did not confirm `stops`, `travel_class`, or `deep_search` params; check the docs.

**Response (trimmed; SerpApi's documented shape, values are the doc example, not a live call):**
```json
{
  "best_flights": [{
    "flights": [{
      "departure_airport": {"id": "CDG", "time": "2026-03-03 10:10"},
      "arrival_airport":   {"id": "LHR", "time": "2026-03-03 10:40"},
      "airline": "British Airways",
      "flight_number": "BA 301"
    }],
    "layovers": [{"duration": 90, "id": "LHR"}],
    "total_duration": 820,
    "price": 520
  }],
  "other_flights": []
}
```
Mapping: price = `price` (in `currency`); carrier = `flights[].airline`; flight no. = `flights[].flight_number`; times = `departure_airport.time` / `arrival_airport.time` (local strings); stops = `len(layovers)` (a missing `layovers` key presumably means nonstop; unconfirmed); `total_duration` in minutes. `other_flights` has the same item shape as `best_flights`.

## Pick 2: Duffel test mode

Realism: **low.** Test mode returns offers from the fake "Duffel Airways" (owner IATA `ZZ`) and possibly external airline sandboxes. Duffel's docs say its schedules and prices are not realistic. Good for demoing a search, select, order flow; bad for real-price displays.

**Signup:** duffel.com, create account, open dashboard, switch to "Developer test mode", create access token (prefix `duffel_test_`). Email verification / business details required: **unknown**. Cost and approval for test mode: none mentioned in docs.

**Auth:** `Authorization: Bearer duffel_test_...` plus header `Duffel-Version: v2`. **Base URL:** `https://api.duffel.com`

**Endpoint:** `POST /air/offer_requests` (query: `return_offers=true` default; `supplier_timeout` 2000-60000 ms, default 20000).
```
curl -X POST "https://api.duffel.com/air/offer_requests?return_offers=true" \
  -H "Authorization: Bearer $DUFFEL_TEST_TOKEN" \
  -H "Duffel-Version: v2" -H "Content-Type: application/json" \
  -H "Accept: application/json" -H "Accept-Encoding: gzip" \
  -d '{"data":{"slices":[{"origin":"LHR","destination":"JFK","departure_date":"2026-11-15"}],"passengers":[{"type":"adult"}],"cabin_class":"economy","max_connections":1}}'
```
Body: `slices[]` (one slice = one-way: origin, destination, departure_date; optional departure_time/arrival_time windows), `passengers[]` (each has `type` OR `age`; repeat the object for more adults), `cabin_class` (first/business/premium_economy/economy), `max_connections` (default 1; 0 = direct only).
Rate limits / free quota: **unknown** (not in the fetched pages). Duffel has a test-scenarios page with predictable routes (not read in detail).

**Response (trimmed; field names from docs, values illustrative, not a live call):**
```json
{"data": {"offers": [{
  "total_amount": "123.45", "total_currency": "GBP",
  "owner": {"name": "Duffel Airways", "iata_code": "ZZ"},
  "slices": [{"segments": [{
    "marketing_carrier_flight_number": "1234",
    "operating_carrier_flight_number": "1234",
    "departing_at": "2026-11-15T09:00:00",
    "arriving_at":  "2026-11-15T12:10:00",
    "stops": []
  }]}]
}]}}
```
Stops = `len(segments)-1` for connections, plus `segments[].stops[]` for technical stops. The offers array location (`data.offers`) and a carrier code field are not confirmed in the fetched text.

## Recommendation detail
- Need real prices in a list UI: SerpApi. Cache by (origin, dest, date) in a local file/dict so 250 credits last; precompute 2-3 demo routes.
- Fallback if SerpApi signup stalls: Duffel (token in minutes, no card mentioned).
- Schedules without price: AeroDataBox only if you can confirm its free quota; not verified here.

## Not verified / caveats
- Amadeus shutdown details come from news snippets and a competitor page; I could not open the PhocusWire article (403) or an Amadeus notice directly. The date (2026-07-17) comes from search summaries.
- Kiwi and Ignav claims come from competing vendors.
- No live API calls were made; sample JSON is documentation-derived, so check field names against a real response.
- Skyscanner/RapidAPI wrappers: not researched.

Sources: duffel.com/docs/api/overview/test-mode; duffel.com/docs/api/v2/offer-requests/create-offer-request; serpapi.com/google-flights-api; serpapi.com/pricing; serpapi.com/blog/whats-new-at-serpapi-july-2025-changelog; phocuswire.com/amadeus-shut-down-self-service-apis-portal-developers; ignav.com/docs/amadeus-self-service-shutdown; ignav.com/docs/kiwi-tequila-alternative
