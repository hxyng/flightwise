# 08 - Fewer and shorter LLM calls in the FlightWise agent loop

**TL;DR (ranked by latency saved)**
1. Cache-first for repeated/demo questions (`api.py` `chat`/`ask` + `demo_cache.py`): saves 100% of LLM time on a hit (17-90 s / 52-67 s -> ~0 s). Today the cache is only a failure fallback.
2. Deterministic intent router + template answer for track/search/list/delay intents (`agent.run_agent`): 2 LLM calls -> 0 (or 1 short sentence). Largest saving on non-demo traffic; this is the LLMCompiler/ReWOO idea with a regex "planner".
3. Text-to-SQL: template the explanation (or drop it for tiny results) in `nl2sql._explain`: 2 calls -> 1, about -40 to -50% of the 52-67 s. Merging SQL+explain into one call is NOT safe (the explanation needs the rows).
4. Shorter prompts/outputs (answer-length budget, fewer tool schemas per turn): second-order, no call removed; gain unmeasured (unknown).

## Premises checked (read-only, `backend\flightwise\`)
- TRUE: `MAX_ITERS = 6`, `num_predict 400`, `think=False`, model default `gemma4:12b` (`config.py:18`).
- PARTLY STALE / worth knowing:
  - The final agent answer is already streamed token by token (`STREAM = True`, `_model_turn` -> `delta` events). Perceived latency is time-to-first-token of call 2, not full decode. Savings below are wall-clock to the full message; the UI gain is smaller for the answer call.
  - Typical agent request is 2 calls (tools, then answer), not 6. Tools are still offered on calls 1-5, so a chatty model can loop; the 90 s tail is probably extra rounds. Unknown: no per-call timing exists in the repo. First step is to log per-call `total_duration`/`prompt_eval_count`/`eval_count` from the Ollama response (`llm.chat` discards them).
  - `t_query_delay_history` calls `nl2sql.ask(question, False)` (explain disabled), so the history route costs 1 SQL call + 2 agent calls = 3 calls, plus up to 1 SQL retry. Text-to-SQL alone is 2 calls (3 on retry).
  - The answer cache is not read first. `demo_cache.get_answer/get_result` are only reached after failure (`api.py:88-117`). Chat answers are keyed by message text alone (no date, no history).
  - Tool work is fast, but each tool already does the ranking in code (`_mark_recommended`, `risk_label`), so the data needed for a template answer is already structured.

## arXiv evidence (abstract-level numbers, each fetched from arxiv.org/abs)
| Idea | Paper (arXiv ID) | Reported result | Transfers to FlightWise? |
|---|---|---|---|
| Parallel function calling via planner + executor | LLMCompiler, 2312.04511 | up to 3.7x latency, 6.7x cost, ~9% accuracy vs ReAct | Partly. Gain comes from batching independent calls and avoiding re-prompting. Our tools are already few; the win is skipping the planning LLM call. |
| Plan first, no LLM between tool calls | ReWOO, 2305.18323 | ~5x token efficiency, +4% on HotpotQA | Yes for token count: one plan, tools, one solver call. Not needed if routing is deterministic. |
| Fused/parallel tool calls | LLM-Tool Compiler, 2405.17438 | up to 40% tokens, 12% latency (per search summary, abstract not opened) | Marginal here. |
| Model cascades | FrugalGPT, 2305.05176 | up to 98% cost cut at GPT-4 quality, or +4% accuracy at same cost | Cost-oriented (API pricing); latency benefit only if a cheap model is much faster. We have one local model. |
| Routing | RouteLLM, 2406.18665 | cost down "over 2 times in certain cases" | Same caveat. Our router would be regex, not learned. |
| Semantic cache | GPT Semantic Cache, 2411.05276 | 61.6-68.8% hit rate, up to 68.8% fewer API calls, >97% positive-hit accuracy; fixed 0.8 threshold | Hit rate comes from open-ended chat traffic. A demo has a small closed set, so exact match plus a few aliases captures most of it. |
| Adaptive cache threshold | vCache, 2502.03771 | per-entry thresholds keep error under a bound | Only relevant if a fuzzy cache is added; unknown benefit at our scale. |
| Parallel answer expansion | Skeleton-of-Thought, 2307.15337 | up to 2.39x across 11 models | Does NOT fit: needs long multi-point answers, ours are ~100 words, and a local 12B has one GPU stream. Skip. |
| Output-length control | TALE, 2412.18547 | 67% fewer tokens at <3% accuracy loss (reasoning tasks) | Directionally valid (decode time ~ output tokens). Our answers are already capped (~100 words, `num_predict 400`), so the headroom is small. |
- Not found: an arXiv paper specifically on template-rendered answers or on early-exit for tool-calling agents. For (b) and (c) the evidence is the above planner/solver papers plus engineering reasoning, not a measured result. Marked "unknown" below.
- Not checked: whether the 2312.04511 gains hold with a single local GPU, where parallel LLM calls would not overlap. The relevant LLMCompiler gain here is fewer calls, not parallel calls.

## Mapping onto the code

### (a) Deterministic intent router (skip the tool-choice call)
- Change: new `route_intent(message, history) -> list[tool_call] | None` called at the top of `agent.run_agent`, before the `for it in range(MAX_ITERS)` loop. When it returns calls, run them through the existing `call_tool` and emit the usual `tool_call`/`tool_result` events, then go to rendering (b). On `None`, fall through to the current loop unchanged.
- Patterns (the repo already has the pieces: `resolve_date`, `_PY_CALL`, `TOOL_NAMES`):
  - flight number `\b([A-Z0-9]{2})\s?(\d{1,4})\b` plus "status|track|where is" -> `track_flight`; plus "notify|keep me updated|watch" -> also `watch_flight`.
  - `\b([A-Z]{3})\b\s*(to|->)\s*\b([A-Z]{3})\b` plus a date phrase accepted by `resolve_date` -> `search_flights`.
  - "what am i watching|watchlist" -> `list_watched`.
  - history-style words (best time, which airline, worst, by month) -> `query_delay_history(question)`.
- Saving: 1 LLM call (the tool-choice call, which also carries the system prompt + 6 tool schemas) on every routed request. If (b) also applies, the answer call goes too: 2 -> 0 calls, 17-90 s -> under ~1 s for track/search/list, by the stated tool time.
- Quality risk: medium. Misrouting (e.g. "AA100" vs an airport code, "SFO to LAX" without a date, city names instead of IATA codes). Mitigation: route only when every required argument is found; otherwise fall back to the LLM. Keep a unit test table of phrasings in `tests\test_agent.py` (its `FakeLLM` already exists). Multi-intent or follow-up messages (uses `history`) should fall back.

### (b) Template-rendered answers; LLM writes at most one sentence
- Change: add `render_answer(name, result) -> str` in `agent.py`, called after the tool results in the routed path (and optionally for the LLM path when the first tool call is a single known tool, replacing call 2).
  - `track_flight`: result is `{"status", "risk"}`. Table or bullets from `departure_local`, `arrival_local`, status, delay minutes, gate, `risk.label`, `risk.pct_delayed_15`, `risk.flights`. Error branch: "history unavailable" (rule already in `system_prompt`).
  - `search_flights`: recommended offer first (already `offers[0]`), its `why`, then the cheapest if different (`_mark_recommended` already computes everything; the 3-row table is spec'd in the prompt). Risk label `unknown` -> "too little history".
  - `delay_risk`: one line from `DelayRisk` fields (`pct_delayed_15`, `flights`, `hour` actually used, `label`).
  - Optional single LLM sentence: pass only the rendered text and ask for one closing sentence with `num_predict` ~60, or skip it. Emit the template as `delta` events first so the UI streams immediately.
- Saving: 1 call (answer) fully, or ~150 -> ~30-60 generated tokens if one sentence is kept. Unknown exact seconds without per-call timing; with the observed totals the answer call is likely the larger share of the 17-90 s, but this is an assumption.
- Quality risk: low on correctness (numbers come straight from tool JSON, so the "never invent numbers" rule becomes structural). Moderate on tone/flexibility: the template cannot respond to the specific wording of a question ("is it cheaper?"). Keep the LLM path for anything the router did not classify.

### (c) Text-to-SQL: merge or template the explanation
- Do not merge SQL generation and explanation into one call. The explanation needs the executed rows, and `ask` retries on SQL errors; one call would force the model to explain data it has not seen.
- Option 1 (recommended): `nl2sql._explain` -> deterministic summary builder. Result shape is already known (`pick_chart`: first column category/time, second the measure). Template: "<top row label> is highest at <v>; <bottom row label> is lowest at <v>. Based on <n> rows." Handles the existing demo questions (best hour, airline reliability, weekday, routes, cancellations by month). Zero LLM calls: 2 -> 1, roughly 50% of the 52-67 s (assuming the two calls are similar; unknown split).
- Option 2: keep the LLM explanation only when columns are not a (label, number) pair or `len(df) == 1`; use the template otherwise.
- Option 3 (UI-side): return rows first, then stream the explanation in a second request so the table/chart appears after one call. Does not cut total work but cuts time-to-result by the explain call. Needs an API change in `api.py` (`/api/ask`).
- Quality risk: low for numbers (template reads the DataFrame). Loses interpretive nuance (e.g. "winter months are worse"). Mitigation: LLM path for non-simple shapes, plus a computed trend word (rising/falling) from the data, not the model.
- Related: `SQL_SCHEMA` JSON generation is capped by `num_predict 400`; a truncated JSON triggers the retry path and a third call. Cheap check: log retries. Unknown how often this happens.
- For SQL generation itself, repeated question shapes ("best time to fly out of <AIRPORT>", "most reliable airline from <AIRPORT>") could use fixed parameterized SQL (as `delay_risk` already does: "Fixed SQL, no LLM"). That would remove the SQL call too: 2 -> 0 calls. Risk: covers only the shapes written; unmatched questions fall back to the LLM.

### (d) Cache (exact match + light fuzzy) for repeated questions
- Change 1: `api.chat_stream` and `api.ask` read `demo_cache.get_answer` / `get_result` before calling the agent / `nl2sql.ask`, instead of only after failure. Replay cached text as `delta` + `message` events so the UI looks the same; keep `CACHED_NOTE` configurable (a "cached" label is honest but noisy for a live demo).
- Change 2: `demo_cache.normalize` is exact after lowercase and punctuation strip. Add alias normalization (strip filler like "please", "can you", "tell me") and, if wanted, an embedding match as in 2411.05276; with ~5 demo questions a keyword-set match is probably enough, so embeddings are likely unnecessary (unknown without real traffic).
- Change 3: key chat answers by (normalized message, resolved date, route) and give them a TTL. Today `save_answer(message, final)` ignores dates and live data: "track AA100" cached once would later replay stale status. Only cache history/BTS answers (static data), not track/search/watch answers.
- Saving: 100% of LLM calls on a hit. Hit rate for the 5 `DEMO_QUESTIONS` is ~100% if warmed with `python -m flightwise.demo_cache warm`; for real users, unknown. The literature figure (61.6-68.8% hits) is for open chat traffic and should not be assumed.
- Quality risk: staleness and false hits. Low for BTS questions (static dataset); high for live flight status, so exclude those.

## Other ideas, ranked low
- Model cascade (FrugalGPT / RouteLLM): a smaller local model (e.g. a 4B) for the tool-choice call only. Saving depends on the speed gap (unknown here); tool-calling reliability of small models is a risk, and this repo already has a text-tool-call fallback parser (`parse_text_tool_calls`), which suggests the model is not fully reliable already. Try (a) first.
- Fewer tool schemas per call: send only the 1-2 relevant `TOOLS` after the router narrows intent. Shrinks prefill; gain unmeasured.
- Drop tools on call 2: after tool results arrive, call `_model_turn(msgs, None)` so the model must answer rather than loop. Removes the multi-round tail (the likely 90 s cases). Risk: the model cannot chain (e.g. track then watch). Mitigate by allowing tools only if the user message has an "and"/"notify" cue.
- Early exit / speculative decoding / prompt caching: out of scope per the brief; not evaluated.
- SoT-style parallel expansion: rejected above.

## Suggested order (smallest first, each independently shippable)
1. Instrument `llm.chat` timings (prompt_eval_count, eval_count, total_duration) to replace the assumptions above.
2. Cache-first in `api.py` for static BTS questions only (d).
3. Templated explanation in `nl2sql._explain` (c, option 1).
4. Router + `render_answer` for track/search/list (a + b), LLM fallback kept.
5. Disable tools after the first tool round (cascade/loop control).

## Not verified
- No code was run; all seconds are derived from the stated measurements, not remeasured.
- arXiv figures are from abstracts; 2405.17438's numbers come from a search summary, not the abstract page. Paper claims were not reproduced on local gemma.
- Per-call latency split (prefill vs decode vs model reload) is unknown.
