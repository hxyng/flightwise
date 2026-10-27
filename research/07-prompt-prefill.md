# 07 - Prompt layout, prefix-cache reuse, and prefill cost (FlightWise agent)

## TL;DR (ranked by expected impact)
1. **Measure first, then stop thrashing the single KV slot.** The agent prompt, the nl2sql prompt and the explain prompt are three unrelated prefixes. With one slot (Ollama default parallel = 1 per the FAQ) each switch re-prefills from token 0. Log `prompt_eval_cached_count` / `prompt_eval_duration` in `llm.py` to confirm, then fix.
2. **Make the history prefix append-only.** `_trim_history` keeps a sliding last-12 window, so once the window slides, every message after the system prompt shifts and only system+tools stays cached. Trim in blocks, and stub old tool results when stored.
3. **Cut tokens that must be prefilled anyway**: project flight results to the fields the prompt actually uses (deterministic field projection, not LLMLingua) and put volatile text (date list) after the static block.
4. `format` constrained decoding is a small per-token cost on a ~50-100 token output. It is not the bottleneck; the 23-column schema + 8 few-shot prefill is. Keep it, just make that prefix cacheable.

## Premise check (primary findings)
- **"Ollama 0.40 (llama.cpp), gemma4:12b": unverified.** I could not confirm these versions or that this model runs on llama.cpp. Current Ollama has its own runner code (the repo tree shows `mlxrunner/` with its own `prefix_cache.go` and `kvcache.go`), so llama.cpp-server flags/logs may not apply. Which engine serves this model: **unknown**; check `ollama serve` logs with `OLLAMA_DEBUG=1`.
- **Sliding-window-attention risk for Gemma: unverified for this model.** llama.cpp prints "forcing full prompt re-processing due to lack of cache data (likely due to SWA)" for SWA models when the cache cannot be partially rolled back (llama.cpp #14163 / #13833; a third-party write-up, particula.tech, describes flat TTFT as the symptom). Gemma-family models use SWA. If cached count stays 0 on an identical prompt, this is the first suspect and layout fixes will not help; only fewer tokens will.
- A third-party book claims `prompt_eval_count` excludes cached tokens. Ollama's own `docs/api.md` (main) says `prompt_eval_count` = tokens in the prompt, `prompt_eval_cached_count` = tokens read from cache, `prompt_eval_duration` = time on **uncached** tokens. Use the cached-count field. Whether version "0.40" already returns it: **unknown**; fall back to `prompt_eval_duration` (a hit shows a collapse in duration).
- Ollama FAQ: default context is 4096; model stays loaded 5 min unless `keep_alive`. Code already sets `keep_alive: "30m"` and a fixed `num_ctx=16384` (good).

## 1. Does Ollama reuse the KV cache across requests?
- Yes in principle: caching is implicit and prefix-based (longest common token prefix with what the slot last held), and `prompt_eval_duration` counts only uncached tokens (docs/api.md). Exact internal behavior in the runner source: **unknown** (I could not fetch the cache source file).
- What breaks reuse (all consistent with prefix semantics; sources: Ollama docs + secondary write-ups, not independently benchmarked):
  - Any token change early in the prompt: system prompt text, today's date, tool list/order (tools render in the template near the top), tool schema edits.
  - Passing `tools` on one call and omitting them on another (the template output changes from the first token).
  - `num_ctx` change: forces a model reload (a secondary report measured 138-142 s per reload on a 17 GB model, Ollama 0.31.1). Constant in `llm.OPTIONS`, so fine.
  - Model unload (`keep_alive` expiry) or another request that overwrote the slot.
  - Re-rendering earlier turns differently than when they were generated (whitespace, stripped thinking, reordered tool_calls).
- **Verify:** call the same request twice, `stream:false`, `think:false`; compare `prompt_eval_cached_count` (expect ~ all but a few tokens on the 2nd call), `prompt_eval_duration` (expect a large drop), and `load_duration` (expect ~0). Then change one early char and confirm cached count collapses.
- Paper context: Prompt Cache (arXiv 2311.04934) reports TTFT cut 1.5-10x on GPU and 20-70x on CPU (body text; the abstract quotes 8x/60x, versions differ). "Don't Break the Cache" (arXiv 2601.06007, cloud providers, not Ollama) reports 41-80% cost and 13-31% TTFT gains, and that caching only the static system prompt while excluding dynamic tool results was more consistent than caching everything (full-context caching sometimes raised latency). Takeaway: static-first layout matters more than caching everything.

## 2. Compressing tool results and schemas
| Technique | Paper numbers | Fit here |
|---|---|---|
| LLMLingua (2310.05736) | up to 20x compression, ~1.5 point metric loss (GSM8K/BBH etc.) | Poor fit: needs a separate small LM per call, token dropping can corrupt numbers/IDs in JSON. |
| LongLLMLingua (2310.06839) | +21.4% on NaturalQuestions at ~4x, 1.4-2.6x end-to-end speedup at ~10k tokens, 94% cost cut on LooGLE | Built for long documents (thousands of tokens); our results are <1k tokens. |
| LLMLingua-2 (2403.12968) | 2-5x compression, 1.6-2.9x e2e latency, compressor 3-6x faster than LLMLingua | Same caveat; BERT-size, but gain on 700-token inputs is likely below its own cost. |
| Tool pruning, "Less is More" (2411.15399) | up to 70% lower execution time, 35-40% better tool accuracy (from a summary; I did not read the paper) | We only have 6 tools; filtering is not worth it. Shortening descriptions is the relevant part; I found **no arXiv paper quantifying description-rewrite compression**: unknown. |
- **Conclusion:** at <1k-token tool results, do lossless-by-construction pruning in code, not neural compression. Your `compact()` already drops nulls and caps lists; the 2,250-char flight result likely still has: raw UTC ISO `departure`/`arrival` next to `*_local`, `origin`/`destination` repeated per offer, long `risk` sub-dicts (`flights`, `avg_dep_delay`, `pct_cancelled`, `hour`, `month`, `carrier`, `origin`). Expected saving: maybe 30-50% of that result (my estimate from reading the code, **not measured**; ~3 chars/token => ~700 tokens now).
- Old tool results ride along for up to 12 messages: the biggest repeated cost. Stub them after the turn (see layout rules).

## 3. Does `format` (JSON schema) constrained decoding slow generation?
- Cost is per decoded token (mask computation), not per prompt token. XGrammar (2411.15100): <40 us/token for JSON Schema; end-to-end TPOT 6.2 ms vs 6.3 ms (Llama-3.1 8B, batch 1, MLC-LLM) = ~1-2% overhead; up to 3x faster than the best baseline on JSON Schema; Outlines 44.2 ms vs XGrammar 6.8 ms TPOT in SGLang (Table 1). The paper compares llama.cpp's grammar engine only in a figure whose numbers I did not retrieve.
- JSONSchemaBench (2501.10868) benchmarks llama.cpp among six engines, but I did not retrieve its speed tables: **llama.cpp/Ollama overhead on gemma: unknown**. Large vocabularies (Gemma ~262k tokens, from memory, unverified) make naive grammar masking costlier.
- Practical: `{"sql": string}` is a trivial schema; output is ~60-120 tokens, so even a pessimistic 2x TPOT on those tokens is ~1-3 s. Prefill of the schema+examples dominates unless cached. Measure by running the identical prompt with and without `format` and comparing `eval_duration / eval_count`.
- Ollama docs warn that `format: "json"` without asking for JSON in the prompt yields whitespace; you use a schema and the prompt asks for JSON, fine. Ollama docs say nothing about combining `format` with `tools`; the code (`llm.chat` docstring) already avoids it.

## 4. Layout rules (static first, dynamic last)
1. Byte-identical static block first: system rules, then tools in a fixed order (build `TOOLS` once; never reorder, never filter per request).
2. Dynamic data after the static block: today's date and the 8-day calendar are currently in the first lines of the system prompt. They change once a day, so the cost is one miss per day (low impact). The 8-day list is also redundant: `resolve_date` already converts "tomorrow"/weekdays in code. Drop it, or move one `Today: ...` line to the end of the system message.
3. Always send the same `tools` array, including the last iteration (`MAX_ITERS`). Passing `None` at `run_agent` last iteration changes the rendered template from token 0 (rare path; instead keep tools and ignore calls).
4. History must be append-only. Trim in blocks (e.g. when >16 messages, cut to 8) so the prefix is stable for ~4 turns, not shifted every turn.
5. Compact old tool results once, when saving to `done.history`, then never re-edit them. One stable stub per call ("search_flights OKC->DEN 2026-10-30: 5 offers, recommended UA123 $189") keeps later prefixes consistent and shrinks the prompt.
6. Store assistant messages exactly as sent (the `final_text` is `.strip()`ed; harmless but note generated-token KV differs from re-rendered text, so the last answer is re-prefilled once).
7. One slot per distinct prefix: either `OLLAMA_NUM_PARALLEL=2` (docs: memory scales with parallel x context) so the agent and nl2sql prompts stop evicting each other, or unify prefixes.
8. Keep `num_ctx`, `keep_alive`, model tag constant; avoid concurrent requests during the demo (they take the other slot).

## Suggested code changes (file:function)
- `backend/flightwise/llm.py:chat` and `chat_stream`: return/log `prompt_eval_count`, `prompt_eval_cached_count` (use `.get`), `prompt_eval_duration`, `eval_count`, `eval_duration`, `load_duration` (streaming: from the final chunk with `done: true`). One log line per call with a label (`agent`, `sql`, `explain`). This is the experiment that decides everything below.
- `backend/flightwise/agent.py:_trim_history`: block trimming (hysteresis) instead of a fixed last-12 window; before returning, replace tool messages older than the last user turn with a one-line stub.
- `backend/flightwise/agent.py:to_model_text` / `compact`: for `search_flights`, project each offer to `{airline_code, flight_numbers, departure_local, arrival_local, price, stops, risk:{label, pct_delayed_15}}` and keep `recommended`/`why`; drop raw ISO `departure`/`arrival` (system prompt tells the model to use `*_local`), per-offer `origin`/`destination`, and risk internals. Re-measure `prompt_eval_count`.
- `backend/flightwise/agent.py:system_prompt`: static text first; move the `Today ... Next days ...` text to the end (or drop the 8-day list). `_date_context` stays only if tests rely on it.
- `backend/flightwise/agent.py:run_agent`: send `TOOLS` on the last iteration too and discard tool calls, to keep the prefix identical.
- `backend/flightwise/data/nl2sql.py:_system_prompt`: already static (schema + examples are the same text each call; `db.get_schema()` should be confirmed deterministic and example order fixed). Put the rules first, schema, then examples; question stays the last user message. Consider cutting example values and few-shot count to the minimum that holds accuracy (measure on the demo question set; I have no paper number for few-shot-count vs SQL accuracy: unknown).
- `backend/flightwise/data/nl2sql.py:ask`: memoize `(question) -> sql` for repeats (demo cache already exists in `data/demo_cache.json`); retries append to messages, which keeps the prefix cached: good.
- Ollama env: consider `OLLAMA_NUM_PARALLEL=2` (test memory), keep `OLLAMA_FLASH_ATTENTION` default.

## Not checked
- Ollama runner source for exact prefix-match/eviction rules and SWA handling; version 0.40 behavior; any gemma4 specifics.
- Actual token counts (all token figures above are char/3 estimates).
- Paper details beyond abstracts/tables retrieved; "Less is More" numbers come from a summary; KV Cache Recycling (2512.11851) appeared in search but was not read.

## Sources
- Ollama API docs `docs/api.md` (github.com/ollama/ollama), docs.ollama.com/faq, docs.ollama.com/capabilities/structured-outputs
- arXiv 2311.04934, 2601.06007, 2310.05736, 2310.06839, 2403.12968, 2411.15399, 2411.15100, 2501.10868
- llama.cpp commits #14163, #13833 (SWA full reprocess); particula.tech SWA write-up (secondary); bmdpat.com num_ctx reload write-up (secondary)
