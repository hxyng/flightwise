# BTS Reporting Carrier On-Time Performance: spec for FLIGHTS table

**TL;DR**
1. Premise holds: transtats still serves prezipped monthly CSVs. Newest is 2026_8 (posted 2026-10-26, 32,030,583 bytes ~ 30.5 MiB zip); a month lags ~1.5-3 months, and some months (2025_8, 2025_12) posted late.
2. URL: `https://www.transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{YYYY}_{M}.zip` (month NOT zero-padded). No Hugging Face/Kaggle parquet mirror verified, so treat mirrors as unknown.
3. SQL below is untested (no Snowflake here); times are hhmm integers, delay causes are NULL unless arrival delay >= 15.

Sources: https://www.transtats.bts.gov/PREZIP/ (directory listing, fetched today), https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FGJ&QO_fu146_anzr=b0-gvzr (field list, ~110 fields).
Confidence: field NAMES and the file list were read from BTS pages. Types, semantics and gotchas below are from my background knowledge of the dataset (not re-verified on the page); verify against the lookup tables / CSV header.

## 1. Download

Recent files (from listing; bytes zipped, ~30 MB each; CSV unzipped roughly 250-300 MB/month, estimate, unknown exactly):

| Month | Posted | Bytes |
|---|---|---|
| 2026_6 | 2026-08-12 | 31,606,062 |
| 2026_7 | 2026-09-21 | 33,075,361 |
| 2026_8 | 2026-10-26 | 32,030,583 |
| 2025_12 | 2026-03-20 | 30,337,431 |

Example (fastest single month, ~31 MB):
```
curl -O https://www.transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2026_7.zip
```
Safer for a hackathon: pre-download 2-3 months (e.g. 2026_6, 2026_7, 2026_8) before the venue wifi; the file is a zip containing one CSV (name inside: `On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_YYYY_M.csv`, unverified).
The directory also lists duplicates with parentheses in the name, `..._(1987_present)_2023_12.zip`; the underscore form without parentheses is the safe one.
Server can be slow/flaky; the PREZIP host is HTTP-served from a gov site, so cache a copy.

DuckDB load (no unzip step needed beyond extracting CSV):
```sql
CREATE TABLE FLIGHTS AS
SELECT * FROM read_csv_auto('On_Time_*.csv', header=true, ignore_errors=true);
-- CSV rows end with a trailing comma -> an extra empty last column (usually auto-named); drop it.
```
Mirrors (none confirmed):
- Hugging Face: searched; found nothing. **Unknown.**
- Kaggle (existence from search results, file formats NOT verified; Kaggle needs login): `bordanova/2023-us-civil-flights-delay-meteo-and-aircraft` (CSV, 2023, BTS-derived, extra weather columns), `robikscube/flight-delay-dataset-20182022` (parquet? unknown), `threnjen/2019-airline-delays-and-cancellations`, `usdot/flight-delays` (2015, 3 CSVs). No direct parquet URL known.
- Recommendation: do not rely on mirrors; use the BTS zip and write the parquet yourself (`COPY FLIGHTS TO 'flights.parquet'`).

## 2. Columns (use these exact names; BTS CSV header names)

| Column | Type | Meaning / gotcha |
|---|---|---|
| FlightDate | DATE | yyyy-mm-dd, local date of scheduled departure |
| Year, Month, DayofMonth | INT | Note: `DayofMonth` lowercase o |
| DayOfWeek | INT | 1=Monday ... 7=Sunday (BTS convention) |
| Reporting_Airline | VARCHAR | Carrier code (unique carrier, e.g. AA, DL, UA, WN, AS, B6, NK, F9, OO, YX) |
| IATA_CODE_Reporting_Airline | VARCHAR | IATA code; usually equal to Reporting_Airline, may differ for historic carriers |
| DOT_ID_Reporting_Airline | INT | DOT carrier id |
| Tail_Number | VARCHAR | Aircraft registration; may be NULL |
| Flight_Number_Reporting_Airline | INT | Flight number (not unique across days; not zero padded) |
| Origin | VARCHAR | 3-letter airport (OKC, DFW). Also OriginCityName, OriginState (2-letter), OriginAirportID |
| Dest | VARCHAR | 3-letter destination. Also DestCityName, DestState |
| CRSDepTime | INT | Scheduled dep, local, **hhmm integer** (905 = 09:05; 5 = 00:05; 2400 can occur for midnight) |
| DepTime | INT | Actual dep hhmm; NULL if cancelled |
| DepDelay | NUMBER | Minutes vs schedule; **negative = early**; NULL if cancelled |
| DepDelayMinutes | NUMBER | DepDelay floored at 0 |
| DepDel15 | INT | 1 if DepDelay >= 15, else 0; NULL if cancelled |
| DepTimeBlk | VARCHAR | Hour block like `0600-0659` (handy for hour-of-day grouping, avoids hhmm math) |
| CRSArrTime / ArrTime | INT | hhmm arrival; ArrTime NULL if cancelled or diverted |
| ArrDelay | NUMBER | Minutes, negative = early; NULL if cancelled/diverted |
| ArrDelayMinutes, ArrDel15 | NUMBER/INT | floored at 0 / 1 if >=15 |
| Cancelled | NUMBER | 1.0 = cancelled, 0.0 = not (often float in CSV; compare `= 1`) |
| CancellationCode | VARCHAR | A=carrier, B=weather, C=NAS (air traffic system), D=security; NULL when not cancelled |
| Diverted | NUMBER | 1.0 = diverted |
| Distance | NUMBER | Statute miles |
| AirTime, ActualElapsedTime, CRSElapsedTime | NUMBER | minutes; NULL if cancelled |
| TaxiOut, TaxiIn | NUMBER | minutes |
| CarrierDelay, WeatherDelay, NASDelay, SecurityDelay, LateAircraftDelay | NUMBER | Minutes attributed to cause. **Populated only for flights with ArrDelay >= 15** (otherwise NULL); sum equals ArrDelay |

Other fields in file: Quarter, Flights (always 1), DistanceGroup, ArrTimeBlk, DepartureDelayGroups, ArrivalDelayGroups, WheelsOff/On, FirstDepTime, TotalAddGTime, LongestAddGTime, Div1..Div5 diversion fields.

Gotchas
- **hhmm times** are not minutes: hour = `FLOOR(CRSDepTime/100) % 24` (2400 -> 0). Never subtract hhmm values.
- **NULLs for cancelled**: DepTime, DepDelay, ArrDelay are NULL. Delay averages must filter `Cancelled = 0` (and usually `Diverted = 0` for arrivals), else cancelled flights silently drop (AVG ignores NULL) and "on time %" denominators go wrong.
- DepDelay/ArrDelay negative for early; use *Minutes columns if you want floor-0 averages.
- Delay-cause columns NULL (not 0) on on-time flights; use COALESCE if summing.
- Times are local to the airport; no time zone column.
- Snowflake folds unquoted identifiers to uppercase; load with the exact header names unquoted and they behave case-insensitively.
- Cancelled can load as FLOAT; `Cancelled = 1` works either way.
- BTS "delayed" convention = 15+ minutes (DepDel15 / ArrDel15).
- Data excludes small carriers (only reporting carriers with >=1% domestic revenue) and has no future/scheduled-only flights.

## 3. Example question -> Snowflake SQL (table FLIGHTS)

Q1. What is the best hour to fly out of OKC?
```sql
SELECT FLOOR(CRSDepTime/100) % 24 AS dep_hour,
       COUNT(*) AS flights,
       ROUND(AVG(DepDelayMinutes),1) AS avg_dep_delay_min,
       ROUND(100*AVG(DepDel15),1) AS pct_delayed_15
FROM FLIGHTS
WHERE Origin = 'OKC' AND Cancelled = 0
GROUP BY 1
HAVING COUNT(*) >= 30
ORDER BY pct_delayed_15 ASC, avg_dep_delay_min ASC
LIMIT 5;
```
Q2. Which airline is the most reliable?
```sql
SELECT Reporting_Airline,
       COUNT(*) AS flights,
       ROUND(100*AVG(CASE WHEN Cancelled = 1 THEN 1 ELSE 0 END),2) AS pct_cancelled,
       ROUND(100*AVG(CASE WHEN Cancelled = 0 AND ArrDel15 = 0 THEN 1 ELSE 0 END),1) AS pct_on_time
FROM FLIGHTS
GROUP BY Reporting_Airline
HAVING COUNT(*) >= 1000
ORDER BY pct_on_time DESC;
```
(pct_on_time uses all flights as denominator, so cancels and diversions count against the carrier.)

Q3. How does delay vary by weekday?
```sql
SELECT DayOfWeek,
       DECODE(DayOfWeek,1,'Mon',2,'Tue',3,'Wed',4,'Thu',5,'Fri',6,'Sat',7,'Sun') AS dow,
       COUNT(*) AS flights,
       ROUND(AVG(DepDelayMinutes),1) AS avg_dep_delay_min,
       ROUND(100*AVG(DepDel15),1) AS pct_delayed_15
FROM FLIGHTS
WHERE Cancelled = 0
GROUP BY DayOfWeek
ORDER BY DayOfWeek;
```
Q4. What are the worst routes (min 200 flights)?
```sql
SELECT Origin, Dest, COUNT(*) AS flights,
       ROUND(AVG(ArrDelayMinutes),1) AS avg_arr_delay_min,
       ROUND(100*AVG(ArrDel15),1) AS pct_arr_delayed_15
FROM FLIGHTS
WHERE Cancelled = 0 AND Diverted = 0
GROUP BY Origin, Dest
HAVING COUNT(*) >= 200
ORDER BY pct_arr_delayed_15 DESC
LIMIT 10;
```
Q5. Cancellations by month (with cause):
```sql
SELECT Year, Month,
       COUNT(*) AS flights,
       SUM(Cancelled) AS cancelled,
       ROUND(100*SUM(Cancelled)/COUNT(*),2) AS pct_cancelled,
       SUM(IFF(CancellationCode='B',1,0)) AS weather_cancels
FROM FLIGHTS
GROUP BY Year, Month
ORDER BY Year, Month;
```
Q6. Delay risk for AA out of OKC, around 14:00 (hour-of-day +/- 1 not applied; exact hour):
```sql
SELECT COUNT(*) AS n,
       ROUND(100*AVG(DepDel15),1) AS pct_delayed_15,
       ROUND(AVG(DepDelayMinutes),1) AS avg_delay_min,
       ROUND(MEDIAN(DepDelay),1) AS median_delay_min
FROM FLIGHTS
WHERE Reporting_Airline = 'AA'
  AND Origin = 'OKC'
  AND FLOOR(CRSDepTime/100) % 24 = 14
  AND Cancelled = 0;
```

## 4. Explainable delay-risk heuristic

Risk = share of flights delayed 15+ min among history for same carrier + origin + scheduled hour + month (optionally same weekday class), with a fallback to broader groups when the sample is small, and a shrinkage toward the origin-wide rate to avoid noisy 3-flight percentages.

```sql
WITH base AS (
  SELECT Reporting_Airline AS carrier, Origin AS origin,
         FLOOR(CRSDepTime/100) % 24 AS hr, Month AS mth,
         CASE WHEN Cancelled = 1 OR DepDel15 = 1 THEN 1 ELSE 0 END AS bad
  FROM FLIGHTS
),
orig AS (SELECT origin, AVG(bad) AS p0 FROM base GROUP BY origin),
cell AS (
  SELECT carrier, origin, hr, mth, COUNT(*) AS n, SUM(bad) AS k
  FROM base GROUP BY 1,2,3,4
)
SELECT c.carrier, c.origin, c.hr, c.mth, c.n,
       ROUND(100 * (c.k + 20*o.p0) / (c.n + 20), 1) AS delay_risk_pct   -- shrinkage, prior weight 20 flights
FROM cell c JOIN orig o USING (origin)
WHERE c.carrier='AA' AND c.origin='OKC' AND c.hr=14 AND c.mth=10;
```
Explanation line for a UI: "Of N past AA flights leaving OKC around 2 pm in October, X% left 15+ minutes late or were cancelled." Show N so users see confidence; flag low-confidence when N < 30. With only a few months loaded (offline fallback) drop `mth` from the grouping. Plain-rate version = `AVG(DepDel15)` from Q6. Note: this treats cancelled as "bad" (decision made here; change `bad` if you want delay only). It uses history only, so it knows nothing about today's weather or inbound aircraft (LateAircraftDelay is a big share of delay minutes, so a tracked flight's inbound leg is the strongest live signal; not covered here).

## Unknowns
- Exact CSV filename inside the zip, uncompressed size, whether the CSV has a trailing empty column (believed yes).
- Any Hugging Face / Kaggle parquet URL.
- Exact DDL types; use `read_csv_auto` / Snowflake `INFER_SCHEMA` and check.
- Whether older (pre-2025) months got revised; not checked.
