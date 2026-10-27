# 06 - Decode speed: gemma4:12b on RTX 3080 Ti Laptop via Ollama

**TL;DR (ranked by expected impact)**
1. Throttling is the primary cause: a 12B Q4 decode is memory-bandwidth-bound (~512 GB/s / 8.4 GB = ~60 tok/s ceiling); 1.8-7 tok/s means the GPU is crippled by SW thermal slowdown/power cap. Fix cooling/power mode first (could be 5-10x).
2. Turn thinking OFF (`think:false`): gemma4 defaults thinking ON, so "150-token answers" may cost 500-3000 generated tokens each. Biggest wall-clock win, zero quality risk for simple tool calls (test it).
3. Smaller model (gemma4:e4b, ~3x fewer active bytes) gives ~2-3x tok/s; do NOT expect speculative decoding/MTP to work in Ollama 0.40 on CUDA (unconfirmed).
4. Flash attention / KV q8_0 / keep_alive: small (<10-15%) decode gains at 16k ctx; safe, cheap.

## Premises checked (read-only commands run)
- `ollama --version` = **0.40.11** (premise said 0.40.9: close enough). `ollama ps`: gemma4:12b, 8.4 GB, 100% GPU, ctx 16384, runner **llamacpp**.
- `ollama show`: 11.9B, Q4_K_M, capabilities include **thinking, default = true**. Params: temperature 1, top_k 64, top_p 0.95. **PREMISE-ADJACENT FINDING:** thinking is on by default; if the agent never passes `think:false`, most time is spent on hidden reasoning tokens.
- `nvidia-smi` snapshot (one sample, model idle, not under load): SM clock **585 MHz** (max 2100), 39 W, **80 C**, throttle bitmask **0x20 = SW thermal slowdown** (not 0x01 idle, not 0x04 power cap). Confirms thermal limiting even with no load; power limit reported N/A. Under-load behavior: unknown (not measured).
- Ollama FAQ: flash attention is auto-enabled when backend/device supports it; `OLLAMA_FLASH_ATTENTION=1` forces. FAQ says nothing about speculative decoding.

## (b) Does throttling explain 1.8-7 tok/s?
- Yes, very likely, but I have no direct measurement of tok/s vs clock on this card: unknown exactly.
- Spec: RTX 3080 Ti Laptop 16 GB GDDR6, 256-bit, ~512 GB/s; TGP 80-175 W by chassis; boost 1125 MHz (80 W) to 1590 MHz (150 W+) ([Notebookcheck](https://www.notebookcheck.net/NVIDIA-GeForce-RTX-3080-Ti-Laptop-GPU-GPU-Benchmarks-and-Specs.588451.0.html)). Decode reads all weights per token: 8.4 GB -> ceiling ~60 tok/s; practical ~35-45 tok/s unthrottled (my estimate, not from a paper).
- At 585 MHz core (28% of max) and 43 W, compute and often memory clocks drop; 1.8-7 tok/s (4-15% of ceiling) is consistent with severe throttling plus CPU contention/thinking length. Variance 1.8 vs 7 suggests fluctuating thermal state.
- Settings to look at (list only, nothing changed):
  - Vendor performance mode (Armoury Crate Turbo/Manual, MSI Center Extreme, Lenovo Legion Performance) set to max; AC power adapter at full wattage (not USB-C/low-watt).
  - Windows Power Mode = Best performance; power plan High performance/Ultimate; "Plugged in" profile.
  - NVIDIA Control Panel: Power management mode = Prefer maximum performance (global); confirm Dynamic Boost / GPU TGP not limited by CPU load.
  - GPU-only/dGPU (MUX) mode instead of Optimus hybrid; fans max (vendor fan curve); raised stand, clean vents, repaste (hardware).
  - Windows Graphics Settings: assign `ollama app.exe`/`ollama.exe` to High performance GPU.
  - Close other GPU/CPU users (browser, game overlays); HAGS on/off is a test variable, effect unknown.
  - Optional power cap via `nvidia-smi -pl` / undervolt in vendor tool (can reduce heat; effect on this chassis unknown).
  - Diagnostic: `nvidia-smi --query-gpu=clocks.sm,clocks.mem,power.draw,temperature.gpu,clocks_event_reasons.active --format=csv -l 1` DURING generation. Bits: 0x04 SW power cap, 0x20 SW thermal, 0x40 HW thermal, 0x80 HW power brake.
- Evidence quality: forum threads on 0x20 exist only for other cards (NVIDIA dev forums); no laptop-specific 585 MHz fix source found.

## Techniques (speedup, Ollama 0.40 support, risk)
| # | Technique | Paper number (arXiv) | Ollama 0.40 on CUDA/llama.cpp runner? | Enable | Risk |
|---|---|---|---|---|---|
| 1 | Fix throttling | n/a (no paper) | n/a | see (b) | Heat/fan noise |
| 2 | Thinking off | n/a | Yes | API `"think": false`; CLI `/set nothink`; `--think=false` | Lower reasoning quality on hard queries; test tool-call accuracy |
| 3 | Smaller model (e4b/e2b) | n/a (bandwidth scaling) | Yes | `ollama pull gemma4:e4b` (not done) | Tool-call quality (see (a)) |
| 4 | Speculative decoding, draft model | 2-3x on T5-XXL, lossless ([2211.17192](https://arxiv.org/abs/2211.17192)) | Release notes mention draft models for speculative decoding (v0.40.5/.7/.10, Nemotron "DFlash draft"), and MLX runner reliability fixes; **no documented Modelfile/env var for gemma4 on llama.cpp+CUDA; not in FAQ**: unknown/likely not usable | none known | Draft needs shared vocab; on a throttled GPU gain shrinks |
| 5 | Gemma 4 MTP drafters | Google claims "up to ~3x", exact same output; MoE 26B may not gain at batch 1 ([Google docs](https://ai.google.dev/gemma/docs/mtp/overview.md.txt)); no 12B numbers found | Third-party blogs say drafters are on Ollama; **Ollama release notes shown mention no MTP**: unverified | unknown | Best-case figure; extra VRAM for drafter |
| 6 | EAGLE | 2.7-3.5x latency on LLaMA2-Chat 70B ([2401.15077](https://arxiv.org/abs/2401.15077)) | No (needs trained head, not in Ollama) | n/a | Needs model-specific head |
| 7 | Medusa | >2.2x (Medusa-1), 2.3-3.6x (Medusa-2) ([2401.10774](https://arxiv.org/abs/2401.10774)) | No | n/a | Needs fine-tuned heads |
| 8 | Lookahead decoding | up to 1.8x MT-bench, 4x code ([2402.02057](https://arxiv.org/abs/2402.02057)) | No in Ollama; llama.cpp has lookahead example only in its CLI | n/a | Extra FLOPs; poor fit for throttled compute |
| 9 | n-gram/prompt-lookup speculation | no paper cited here | llama.cpp has it; not exposed by Ollama (unknown) | n/a | Gains only when output copies input |
| 10 | Flash Attention | ~2x over FlashAttention-1 on A100 for training/attention kernel ([2307.08691](https://arxiv.org/abs/2307.08691)); at batch 1, 16k ctx decode effect is small (my judgement) | Yes, auto when supported | `OLLAMA_FLASH_ATTENTION=1` (Windows user env var, restart server) | Low |
| 11 | KV-cache quantization | KIVI 2-bit: 2.6x less peak memory, 2.35-3.47x throughput via bigger batches ([2402.02750](https://arxiv.org/abs/2402.02750)); batch-1 gain is minimal | Yes q8_0/q4_0 (FAQ); needs FA | `OLLAMA_KV_CACHE_TYPE=q8_0` | q8_0 "very small loss"; q4_0 noticeable at large ctx |
| 12 | Weight quantization | LLM.int8(): half memory, no loss ([2208.07339](https://arxiv.org/abs/2208.07339)) | Q4_K_M already; Q3/Q2 would be faster but lossy | n/a | Tool-call JSON fidelity drops at low bit (anecdotal) |
| 13 | Reduce num_ctx (16384 -> 4096-8192) | n/a | Yes | Modelfile `PARAMETER num_ctx 8192` / API option | Truncation if prompt is long; modest decode gain |
| 14 | keep_alive / avoid reload | n/a | Yes | `OLLAMA_KEEP_ALIVE=-1` (FAQ default 5 min) | Holds VRAM |

Note on #4-9: with a throttled core, speculative methods trade extra compute for fewer weight reads; they help only when decode is bandwidth-bound. Their real-world gain on a laptop 3080 Ti is unknown.

## (a) Is a smaller variant the biggest single win?
- Sizes (Ollama library): `gemma4:e2b` 4.6-7.5 GB, `gemma4:e4b` 6.6-9.5 GB (default `latest`), `gemma4:12b` 7.7-8.0 GB, `26b` (MoE, ~3.8B active) 16-19 GB, `31b` 20 GB ([Ollama](https://ollama.com/library/gemma4)). Download size is misleading: E-models include large per-layer embeddings; active compute is ~2B/4B. Actual decode gain of e4b vs 12b on this GPU: unknown, I expect ~2-3x if bandwidth-bound (estimate).
- **It is NOT the biggest win** if the GPU is at 585 MHz: a 4B at 28% clocks is still throttled; fix throttling and thinking first (ranked above). It is the biggest *software* change after those.
- Quality for tool calling: I found **no controlled BFCL/tau-bench comparison of E4B vs 12B**; BenchLM shows only 2 shared (knowledge) benchmark rows ([BenchLM](https://benchlm.ai/md/compare/gemma-4-12b-vs-gemma-4-e4b.md)). tau2-bench reported only for 31B (86.4% per secondary reviews). Anecdotes: a 12B QAT build had unreliable tool calls; an Ollama parser bug put E4B tool calls into the reasoning field ([Verdent review](https://verdent.ai/guides/gemma-4-coding-agent-review) and related, anecdotal). Conclusion: measure on your own tool-call eval set before switching.
- Alternatives (4-8B other families): no evidence gathered; unknown.

## Recommended order for tonight
1. During one generation, run the `nvidia-smi -l 1` query above; if reasons show 0x20/0x04, apply the (b) settings (power mode, AC, MUX, fans). Re-measure tok/s.
2. Set `think:false` on API calls; compare latency and tool-call correctness on 10-20 sample queries.
3. Set `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_KEEP_ALIVE=-1`, num_ctx 8192 if prompts fit.
4. Only then A/B `gemma4:e4b` (pull needed; not done here) on your tool-calling set.
5. Skip speculative/EAGLE/Medusa/lookahead tonight: no supported path found.

## Not checked / gaps
- No measured tok/s vs clocks; no Ollama issue tracker search for gemma4 CUDA slowness; whether Ollama 0.40.11 enables MTP for gemma4 on llama.cpp (unknown); Gemma-specific MTP speedups on RTX-class GPUs (unknown); paper numbers are abstract-level from A100/70B setups, not this hardware.

Sources: arXiv abstracts linked above; [Ollama FAQ](https://github.com/ollama/ollama/blob/main/docs/faq.mdx); [Ollama releases](https://github.com/ollama/ollama/releases); [Google MTP docs](https://ai.google.dev/gemma/docs/mtp/overview.md.txt).
