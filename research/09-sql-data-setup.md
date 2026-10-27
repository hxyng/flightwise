# FlightWise: Snowflake data setup and text-to-SQL speed/accuracy

## TL;DR (ranked by impact)
1. **Template-first, LLM fallback** removes the 25-35 s call for the common shapes (your 8 examples are already 8 templates). Biggest win by far; the data side cannot fix LLM latency.
2. **Dynamic few-shot (top-3 by masked-question similarity) over a larger bank (~20-30 pairs)** cuts prompt tokens and, per DAIL-SQL, does not cost accuracy. Do NOT build schema pruning: 23 columns is too small to benefit.
3. **15-question execution-result test set** (section 4) so every change above is measured, not guessed.
4. **Aggregate tables: optional and low value.** Queries are already 0.1-0.5 s, so they give no speed gain, and re-aggregable counts make the model's SQL *harder*, not simpler. Skip MV / clustering / search optimization.

## 0. Premises checked
- **Speed premise holds, and it implies the data side is nearly irrelevant.** 0.1-0.5 s of query vs 25-35 s of LLM: even a 10x faster table saves <0.5 s. (Query time is your premise; not re-measured.)
- **Trial edition: UNKNOWN.** Snowflake docs say you pick the edition at sign-up; the trial page states no default. Materialized views and search optimization require Enterprise ([MV docs](https://docs.snowflake.com/en/user-guide/views-materialized), [SOS docs](https://docs.snowflake.com/en/user-guide/search-optimization-service)). Check with `SELECT CURRENT_ACCOUNT()` then Snowsight Admin > Accounts, or try `CREATE MATERIALIZED VIEW` once. Trial lasts 30 days or until credits run out ([trial docs](https://docs.snowflake.com/en/user-guide/admin-trial-account)). Hybrid tables and external network access are unavailable on trials.
- **Path note:** `nl2sql.py` is at `backend\flightwise\data\nl2sql.py` (not `backend\flightwise\`).
- **Retry cost:** `ask()` retries once on any failure, so a bad first SQL doubles latency to ~60 s. Raising first-try accuracy is therefore also a speed win.
- **Prompt facts from code:** the system prompt embeds all 8 examples every call; the model must also obey "runs on DuckDB and Snowflake", which constrains any new table (it must exist in both backends).
- Whether the 25-35 s is prompt-processing or decoding: unknown (out of scope). Prompt trimming helps the first; short outputs help the second.

## 1. Prompt side (evidence)
| Technique | Evidence | Relevance to FlightWise |
|---|---|---|
| Example selection by similarity | DAIL-SQL, [2308.15363](https://arxiv.org/abs/2308.15363), GPT-4 EX on Spider-dev, 1/3/5-shot: Random 77.4/79.4/79.5; Question-similarity 78.8/79.2/79.9; Masked-question-similarity 79.1/81.5/82.0; DAIL selection 80.2/81.7/82.4 | 3 well-chosen shots beat 5 random ones (81.7 vs 79.5). Mask entity values (airport/carrier codes, months) before similarity. |
| Token cost | DAIL-SQL reports ~1,600 tokens/question on Spider-dev (figure from a repo mirror via search summary, not read in the paper text); full-information example organization costs "several times" more than DAIL organization | Your 8 pairs are roughly 700 tokens (my estimate, not counted). Top-3 saves ~400-450 tokens/call. Speedup in seconds: unknown. |
| Small models gain most from shots | Same paper: LLaMA-7B 13.0 zero-shot to 30.9 5-shot; LLaMA-13B 20.3 to 38.8 (Spider-dev EX) | Few-shot is essential for a 12B local model; do not drop to zero-shot. |
| Rule/format instructions | Same paper: dropping "with no explanation" rule lowers EX 1.3-2.4 pts; foreign keys +0.6-2.9 | Keep your output-format rules; no FKs needed (single table). |
| Schema pruning | CHESS, [2405.16755](https://arxiv.org/abs/2405.16755): schema selector cuts LLM tokens ~5x, +~2% on a 4,337-column schema; ablating select_tables / select_columns cost -6.1 / -5.4 EX on a BIRD-dev subsample | Gains come from hundreds/thousands of columns. At 23 columns, skip. |
| "Is linking needed?" | Maamari et al., [2408.07702](https://arxiv.org/abs/2408.07702): strong LLMs can skip linking when the schema fits context; for smaller/older models linking often still pays | Contradicts nothing here: a 23-column table fits easily. Spend effort on examples, not linking. |
| Decomposition | DIN-SQL, [2304.11015](https://arxiv.org/abs/2304.11015): ~+10% over simple few-shot across 3 LLMs; Spider test 85.3, BIRD test 55.9 | Multi-call pipeline: at 30 s/call it is unaffordable. Do not adopt. |
| Zero-shot cleanup | C3, [2307.07306](https://arxiv.org/abs/2307.07306): 82.3 Spider test, ChatGPT zero-shot (Clear prompting, hints, consistency voting) | Voting = several calls; skip. "Clear prompting" (drop irrelevant schema) is the only free part. |
| Small-model BIRD levels | E-SQL [2409.16751](https://arxiv.org/abs/2409.16751): Qwen2.5-Coder-7B 53.59 EX BIRD-dev; Feather-SQL [2503.17811](https://arxiv.org/abs/2503.17811): SLM ceiling 54.76 without fine-tuning; SLM-SQL [2507.22478](https://arxiv.org/abs/2507.22478): fine-tuned 1.5B 67.08 | Ceiling for generic small models on hard multi-table BIRD is ~50-55%. Your task (one table) is far easier, but no published figure for gemma-class 12B on single-table: unknown. This is why you must measure locally. |
| RESDSQL | [2302.05965](https://arxiv.org/abs/2302.05965): decouples schema linking from skeleton parsing (fine-tuned seq2seq) | Not applicable to prompting a chat model; no numbers verified. |

**Column-value hints.** C3 "calibration with hints" and CHESS value retrieval motivate this; I found no clean ablation number for either. For FlightWise it is cheap: list valid values inline (carrier code to name map, ~15 carriers; MONTH 6/7/8; DAY_OF_WEEK 1-7 and which day is 1; DEP_HOUR 0-23; the full ORIGIN list is too long, so extract the airport code from the question in code and inject only "ORIGIN codes mentioned: DFW"). Also state NULL semantics (DEP_DEL15 and DEP_DELAY are NULL for cancelled flights, so AVG ignores them).

**Concrete prompt changes**
1. Move the 8 pairs into a bank of ~25 (add: by-airport, by-carrier-at-airport, weekday x hour, delay causes by carrier, busiest hours, monthly trend, top N routes from an airport, cancellation causes via CANCELLATION_CODE, distance bucket).
2. Retrieve top-3 by similarity of entity-masked question (TF-IDF or a small local embedding; with ~25 items even Jaccard works). Always include the one example whose SQL shape matches the top intent.
3. Replace the full column table with the pruned, value-hinted description (static prune only: drop columns the question never needs such as FLIGHT_NUM unless it is mentioned).
4. Enforce short output: `SELECT` only, no comments. Cache by normalized question text (the demo cache already exists).

## 2. Data side
**Features vs this table (1.84M rows, roughly tens of MB: size estimate, not measured).**
| Feature | Edition / trial | Verdict |
|---|---|---|
| Result cache | On by default; 24 h retention (reset on reuse, max 31 days); requires exactly identical query text and unchanged data ([docs](https://docs.snowflake.com/en/user-guide/querying-persisted-results)). Edition note: page is silent, treat as unknown | Free win for template SQL (fixed text). LLM output text varies, so low hit rate there. Save time per hit: <0.5 s. |
| Clustering / auto clustering | Docs: aimed at multi-TB tables with many micro-partitions ([docs](https://docs.snowflake.com/en/user-guide/tables-clustering-keys)); edition not stated | Skip. Table is a handful of micro-partitions. |
| Search optimization | Enterprise+; targets selective point lookups, not aggregations | Skip. |
| Materialized view | Enterprise+; single table, no HAVING/ORDER/LIMIT/window, background serverless credits on every base change | Skip. Data loads rarely; a CTAS table is simpler and works on any edition. |
| Plain CTAS aggregate table | Any edition | Only worth it for accuracy/simplicity, see below. |

**Why aggregate tables are marginal.** To stay re-aggregatable you must store counts and sums, so percentages become `100.0*SUM(DELAYED15)/NULLIF(SUM(DEP_FLIGHTS),0)` instead of `100.0*AVG(DEP_DEL15)`. That is a harder expression for a 12B model and a new failure mode (averaging pre-averaged rates). Gain exists only if you want questions answered from a tiny, curated surface. If you still want it, run once (works on Snowflake; DuckDB needs the same CTAS minus the fully-qualified name):

```sql
CREATE OR REPLACE TABLE FLIGHTWISE.PUBLIC.FLIGHTS_AGG AS
SELECT CARRIER, CARRIER_NAME, ORIGIN, MONTH, DAY_OF_WEEK, DEP_HOUR,
       COUNT(*)                    AS FLIGHTS,
       SUM(CANCELLED)              AS CANCELLED_FLIGHTS,
       COUNT(DEP_DEL15)            AS DEP_FLIGHTS,      -- denominator for delay rate
       SUM(DEP_DEL15)              AS DELAYED15,
       COUNT(DEP_DELAY)            AS DEP_DELAY_N,
       SUM(DEP_DELAY)              AS DEP_DELAY_SUM,
       COUNT(ARR_DEL15)            AS ARR_FLIGHTS,
       SUM(ARR_DEL15)              AS ARR_DELAYED15,
       SUM(CARRIER_DELAY)          AS CARRIER_DELAY_MIN,
       SUM(WEATHER_DELAY)          AS WEATHER_DELAY_MIN,
       SUM(NAS_DELAY)              AS NAS_DELAY_MIN,
       SUM(LATE_AIRCRAFT_DELAY)    AS LATE_AIRCRAFT_DELAY_MIN
FROM FLIGHTWISE.PUBLIC.FLIGHTS
GROUP BY CARRIER, CARRIER_NAME, ORIGIN, MONTH, DAY_OF_WEEK, DEP_HOUR;

CREATE OR REPLACE TABLE FLIGHTWISE.PUBLIC.FLIGHTS_ROUTE_AGG AS
SELECT CARRIER, CARRIER_NAME, ORIGIN, DEST, MONTH,
       COUNT(*) AS FLIGHTS, SUM(CANCELLED) AS CANCELLED_FLIGHTS,
       COUNT(DEP_DEL15) AS DEP_FLIGHTS, SUM(DEP_DEL15) AS DELAYED15,
       COUNT(DEP_DELAY) AS DEP_DELAY_N, SUM(DEP_DELAY) AS DEP_DELAY_SUM
FROM FLIGHTWISE.PUBLIC.FLIGHTS
GROUP BY CARRIER, CARRIER_NAME, ORIGIN, DEST, MONTH;

-- Row counts are UNKNOWN until run; verify the shrink is real (if close to 1.84M, drop the idea):
SELECT (SELECT COUNT(*) FROM FLIGHTWISE.PUBLIC.FLIGHTS_AGG) AS agg_rows,
       (SELECT COUNT(*) FROM FLIGHTWISE.PUBLIC.FLIGHTS_ROUTE_AGG) AS route_rows;
-- Reconcile (must return 0 rows):
SELECT 1 FROM (SELECT SUM(FLIGHTS) f, SUM(DELAYED15) d FROM FLIGHTWISE.PUBLIC.FLIGHTS_AGG) a,
              (SELECT COUNT(*) f, SUM(DEP_DEL15) d FROM FLIGHTWISE.PUBLIC.FLIGHTS) b
WHERE a.f <> b.f OR a.d <> b.d;
```
Cost of this option: two tables mean the model must choose one (needs a routing rule in code), and every example must be rewritten. It does not cover per-day (FL_DATE) questions; keep FLIGHTS for those. Prefer instead a plain **VIEW** with friendlier names over FLIGHTS only if value-hint quality is the real problem.

## 3. Template first, LLM fallback
Evidence: AWS reports parameterized templates cut end-to-end text2SQL latency ~80% and tokens >50% ([blog](https://aws.amazon.com/blogs/architecture/reducing-text2sql-latency-with-parameterized-query-templates/), vendor production claim, not peer reviewed). LLMSigCache, [2602.19811](https://www.alphaxiv.org/abs/2602.19811), reports 85-90% backend compute reduction from NL/SQL caching (I read only the summary). Snowflake's Cortex Analyst "verified queries" is the same idea, but trial availability is unknown (AI features are off by default on self-service trials until a card is added) and it is not local, so do it in code.

Design (all in `nl2sql.ask`, before `_generate`):
1. **Extract slots in code, no LLM:** carrier (name/synonym/IATA to code), origin and dest airports (IATA code or city via ORIGIN_CITY lookup), month name, hour ("5pm" = 17), weekday, top-N. Build the gazetteer from `SELECT DISTINCT` at startup.
2. **Classify intent** with keyword/regex rules, then confirm by similarity to canonical questions (threshold tuned on the test set). Intents mapped to the existing pairs: best_hour(origin), airline_reliability, dow_pattern, worst_routes(origin?), monthly_cancellations, delay_causes(origin|carrier), risk(carrier,origin,hour) (already `delay_risk`), daily_trend(carrier,month).
3. **Fill parameterized SQL** with bound literals via existing `_lit` / int casts (injection-safe; templates still pass `check_sql`).
4. **Fallback to the LLM** when intent confidence is low or a required slot is missing; ask a clarifying question rather than guess.
5. **Optional hybrid:** have the LLM emit only `{intent, slots}` JSON (~20 output tokens) instead of full SQL, and keep SQL in templates. Shorter decoding should be faster; magnitude unknown, measure it.
6. Log every fallback question; each recurring one becomes a new template or bank example.

Expected coverage: unknown until you log real traffic; the 8 shapes are the likely head of the distribution.

## 4. Quick evaluation (15 questions, ~2 minutes without LLM)
Score by **execution result**, not SQL string (same measure as Spider/BIRD EX). For each question, write the gold SQL by hand once; store its result as the expected set; compare after sorting rows and rounding to 1 decimal; also record SQL-valid, retry-used, latency, route taken (template/LLM). Do not hand-copy expected numbers; generate them from gold SQL and freeze in `eval/expected.json`.

| # | Question | Check |
|---|---|---|
| 1 | Best hour to fly out of ORD? | per-hour delay % list; min row matches |
| 2 | Which airline has the lowest cancellation rate? | top row carrier = gold |
| 3 | Delay by day of week for United | 7 rows, UA only |
| 4 | Worst 10 routes from ATL | 10 rows, ORIGIN=ATL |
| 5 | Cancellations per month | 3 rows (6,7,8) |
| 6 | What causes delays at DEN? | 4 cause rows sum to gold |
| 7 | Delay risk Delta from ATL at 8am | matches `delay_risk()` output |
| 8 | Daily delay rate for Southwest in August | ~31 rows |
| 9 | Busiest airport by flights | single row = gold |
| 10 | Average departure delay by hour for JFK | 24-ish rows |
| 11 | Is Friday worse than Tuesday? | two-day compare = gold |
| 12 | Longest flights with highest delay | DISTANCE-based gold |
| 13 | Weather delay minutes by carrier | carrier rows |
| 14 | Worst month for delays at LAX | one row = gold |
| 15 | Flights from SEA to Hawaii (not in data?) | adversarial: must return empty or ask, no invented data |

Metrics: EX accuracy, template-hit rate, p50/p95 latency, first-try-valid rate. Run baseline now (all-8-examples prompt), then after each change; a change ships only if EX does not drop. Questions 5-8 should hit templates; 9-15 should exercise the LLM fallback and few-shot retrieval. Test-set size of 15 gives wide error bars (one miss = 6.7 points): treat differences under 2 questions as noise.

## Not checked
DAIL-SQL tokens/question primary-source figure; RESDSQL/C3 token numbers; whether result cache and clustering are edition-gated; actual trial edition; actual aggregate row counts; any gemma-12B single-table benchmark; whether latency is prompt- or decode-bound.
