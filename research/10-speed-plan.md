# 10 - Speed plan: what to change, ranked (synthesis of 06–09 + local measurements)

Sources: `06-decode-speed.md`, `07-prompt-prefill.md`, `08-agent-loop.md`, `09-sql-data-setup.md`,
plus measurements on this laptop (2026-10-26, gemma4:12b Q4_K_M, Ollama 0.40.11, RTX 3080 Ti Laptop).

## What we measured
Same agent request (system prompt + 6 tools + "What's the status of AA100?", ~1,000 prompt tokens) sent 3 times:

| call | prompt tokens | from cache | prefill | decode (35 tokens) | tok/s |
|---|---|---|---|---|---|
| 1 | 999 | 962 | 1.91 s | 12.4 s | 2.8 |
| 2 (identical) | 999 | 994 | **0.44 s** | 34.4 s | 1.0 |
| 3 (1 char changed at start) | 1,000 | **0** | **42.5 s** | 26.0 s | 1.3 |

GPU during the run: 585–1,237 MHz of 2,100 max, 38–43 W, 79–80 °C, throttle reason `0x20` (SW thermal slowdown).

Two conclusions:
1. **Decode is throttled to 1–3 tok/s.** Report 06 estimates ~35–45 tok/s unthrottled (bandwidth ceiling ~60). That's a 10–30x gap that no software change closes.
2. **Prefix caching works** (report 07's sliding-window worry is false here), **and a cache miss costs ~40 s per 1,000 tokens** at throttled speed. Every time the agent prompt, the SQL prompt and the explain prompt replace one another in Ollama's single cache slot, the next call pays that again. This is the largest software-side cost, and none of the reports could see it without measuring.

## Ranked plan
| # | Change | Expected saving | Effort | Source |
|---|---|---|---|---|
| 1 | **Stop the thermal throttle** (user): cooling, vendor Turbo mode, Windows Best performance, close other GPU apps | decode 1–3 → tens of tok/s (estimate) | 5 min, no code | 06 + measured |
| 2 | **One cache slot per prompt family**: `OLLAMA_NUM_PARALLEL=3` (agent, SQL, explain), then restart Ollama. Check VRAM fits (8.4 GB model; KV per slot × 3 at 16k ctx; drop `num_ctx` to 8192 if needed) | ~40 s per avoided miss | env var + restart | 07 + measured |
| 3 | **Keep every prefix byte-stable**: move the date/8-day calendar to the end of the system prompt (or drop it; `resolve_date` already handles dates in code), always send the same `TOOLS` (also on the last iteration), trim history in blocks, and stub old tool results | keeps hits at ~0.4 s prefill | small, `agent.py` | 07 |
| 4 | **Cache-first for static BTS questions**: serve `demo_cache` before calling the model, not only on failure. Never for live track/search answers | 100% of model time on a hit | small, `api.py` | 08 |
| 5 | **Template the SQL explanation** (`nl2sql._explain`): top/bottom row plus count from the DataFrame; LLM explanation only for odd result shapes | 1 of 2 SQL calls (~half of 52–67 s) | small | 08 |
| 6 | **Template the numbers in agent answers** (track / search / risk) and let the model add at most one sentence | most of the ~150-token answer decode | medium | 08 |
| 7 | **Log per-call timings** in `llm.py` (`prompt_eval_count`, `prompt_eval_cached_count`, durations) so each change above is measured | — | tiny | 07, 08 |
| 8 | Test `gemma4:e4b` **after** fixing the throttle, on a 15-question tool-call/SQL check set | ~2–3x decode (estimate) | pull + eval | 06, 09 |

## Conflicts resolved between reports
- **Dynamic few-shot vs prompt caching.** Report 09 recommends retrieving the top-3 most similar SQL examples per question (DAIL-SQL, arXiv 2308.15363: 3 well-chosen shots 81.7 vs 5 random 79.5 EX). That changes the prompt prefix on every question and turns a 0.4 s cache hit into a ~40 s miss. **Keep the fixed 8 examples** (cached once). If retrieval is ever added, append the retrieved examples *after* the static block.
- **Templates vs "it's an AI agent".** Templates (#5, #6) make numbers exact and fast, but if everything is templated there's little AI left to show judges. Keep the model doing what only it can do: choosing tools, chaining track → watch, writing SQL for new questions. Template only the rendering of numbers it already has.
- **Intent router (report 08, idea a).** Skipping the tool-choice call with regex is the biggest saving per request, but it removes the agent's visible decision-making from the demo. Defer it; #1–#3 should make tool choice fast enough.

## Explicitly skipped
Speculative decoding / EAGLE / Medusa / lookahead (no supported path in Ollama 0.40 for gemma4 on CUDA; report 06). LLMLingua-style compression (inputs < 1k tokens; report 07). Schema pruning (23 columns is too small; 09). Aggregate tables, materialized views, clustering (queries already 0.1–0.5 s; aggregates make the model's SQL harder; 09). DIN-SQL decomposition and voting (more calls; 09).

## Not verified
- Unthrottled tok/s on this GPU (estimate only).
- Whether 3 parallel slots fit in 16 GB VRAM at `num_ctx` 16384.
- Accuracy impact of templated explanations and of e4b; needs the 15-question set from report 09.
- Arxiv figures are mostly abstract-level, from other hardware.

## Results (applied 2026-10-26, measured with `backend/scripts/bench_speed.py`)
Same 5-step demo sequence, mock flight providers, Snowflake data. Baseline = last commit run from a clean worktree.
Raw data: `research/bench-before.json`, `research/bench-after.json`. (`bench-before-invalid.json` is a first
baseline attempt that loaded `agent.py` mid-edit and overlapped another session's model calls; ignore it.)

| step | model calls | generated tokens | wall time |
|---|---|---|---|
| "When's the best time to fly out of OKC?" | 2 → 1 | 117 → 73 | 124.5 → 7.3 s |
| "Track AA100 and keep me posted" | 2 → 2 | 190 → 93 | 72.6 → 30.8 s |
| "Which airport has the most cancelled flights?" | 2 → 0 (cache) | 62 → 0 | 24.3 → 0.0 s |
| "Find me a flight OKC to DEN this Friday" | 2 → 2 | 279 → 59 | 84.8 → 35.0 s |
| "Which day of the week has the worst delays?" | 2 → 0 (cache) | 116 → 0 | 45.0 → 0.0 s |
| **total** | **10 → 5** | **764 → 225 (−71%)** | **351 → 73 s** |

**Read the wall times with care.** GPU speed swung from 0.7 to 38 tokens/s between and within runs (thermal
throttling), so most of the wall-time gap is the GPU, not the code. Generated tokens and model calls are the
fair measure of the code change; they don't depend on GPU speed. The "after" run also started on a cool GPU.

What changed:
- **#2 (separate cache slots): not applied.** The baseline showed every call already reading 61–99% of its
  prompt from cache, with 0.15–2.8 s prefill, across agent, SQL and explanation prompts. Ollama 0.40 keeps
  several prompt prefixes, so a second slot would only cost VRAM.
- #3 stable prompts, #4 cache-first, #5 templated SQL summaries, #6 templated agent facts with a 60-token
  advice sentence, #7 per-call timing logs: applied.
- Cache hits re-render their summary from the saved rows, so answers saved by older code use the new wording.
