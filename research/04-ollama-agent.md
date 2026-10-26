# Ollama local tool-calling agent + text-to-SQL (checked 2026-10-26)

**TL;DR**
1. All three local models (gemma4:12b, hermes-gemma4:12b, qwen3.6:27b) report `tools` + `thinking` in `ollama show`. Best laptop demo: **gemma4:12b** (7.6 GB, `think=False` for speed); qwen3.6:27b (17 GB) only if RAM/VRAM allows.
2. PREMISE LIKELY STALE: qwen2.5-coder:7b is tagged `tools`, 32K ctx, but last updated ~1 year ago; "best small SQL model" is unverified (benchmarks: unknown). qwen3-coder has NO small size (smallest = 30b MoE, 19 GB, 3.3B active). Don't add a second model for the demo: use gemma4:12b + `format=<schema>` for SQL.
3. Gotchas: set `num_ctx` explicitly (default 4k if <24 GiB VRAM!), `keep_alive`, `think=False`, return tool results as `role:"tool"` + `tool_name`; cap loop iterations; validate SQL read-only.

## 1. Tool calling: /api/chat shape (docs.ollama.com/capabilities/tool-calling, /api/chat)
Request (`stream` defaults to **true** on /api/chat):
```json
{"model":"gemma4:12b","stream":false,"think":false,"keep_alive":"30m",
 "options":{"num_ctx":16384,"temperature":0},
 "messages":[{"role":"user","content":"Track UA100"}],
 "tools":[{"type":"function","function":{"name":"track_flight",
   "description":"Live status of a flight","parameters":{"type":"object",
   "required":["flight_number"],"properties":{"flight_number":{"type":"string"}}}}}]}
```
Response: `message` has `role`, `content`, `thinking` (if enabled), `tool_calls`, plus top-level `done`, `done_reason`, duration/token counts.
`tool_calls[i] = {"type":"function","function":{"index":0,"name":"track_flight","arguments":{"flight_number":"UA100"}}}`
- `arguments` is an **object, not a JSON string** (differs from OpenAI). **No `id`** field documented.
- Return results: append the assistant message as-is, then one message per call, in order:
  `{"role":"tool","tool_name":"track_flight","content":"<string>"}` (matched by `tool_name`, not call id). Parallel calls = several entries in `tool_calls`.
- Streaming: `stream:true` works with tools; accumulate `message.thinking`, `message.content`, and `message.tool_calls` (extend list) across chunks, then append ONE assistant message with all three plus the tool results. Reasoning tokens arrive before content.
- `think`: bool, or string level for models that define levels (gpt-oss low/medium/high); null = model default; numbers unsupported. Local models show `levels: false, true`, default **true** (thinking is ON by default = slow; pass `think=False` for the router step). Docs do not say whether thinking must be echoed back; the official agent loop appends the whole `response.message` (includes thinking), so do that.
- Python `ollama` package: `chat(model, messages, tools=[fn,...] or schema dicts, think=..., format=..., options=..., keep_alive=...)`. Functions as tools: schema auto-built from type hints + Google-style docstring. Call with `fn(**call.function.arguments)`. Response is object-style (`resp.message.tool_calls`).

## 2. Structured outputs (docs.ollama.com/capabilities/structured-outputs)
- `format` = `"json"` or a JSON-schema dict, on /api/chat and /api/generate. Python: `format=Model.model_json_schema()`, parse `Model.model_validate_json(resp.message.content)`.
- Tips from docs: `temperature: 0`; also describe/paste the schema in the prompt. Not supported on Ollama cloud.
- Interaction with thinking/tools: docs silent -> **unknown**. Do not combine `format` with `tools` in one request; use separate calls (SQL step = `format` only, `think=False`).

## 3. Models (local `ollama show` + ollama.com library pages)
| model | local size | capabilities (local show) | notes |
|---|---|---|---|
| gemma4:12b | 7.6 GB, Q4_K_M, 11.9B | completion, vision, audio, tools, thinking | ctx 262144 native; renderer/parser `gemma4` built in; default temp 1 |
| hermes-gemma4:12b | 7.6 GB | same | same arch/parser; baked `num_ctx 32768`, `num_predict 8192`, temp 0.7, top_p 0.9 (quality vs base: unknown) |
| qwen3.6:27b | 17 GB, Q4_K_M, 27.8B | completion, vision, tools, thinking | library has 27b/35b; agentic-coding focus; parser `qwen3.5`; presence_penalty 1.5 default |

Also installed: gemma4:latest (9.6 GB), hermes-gemma4:latest. Library page tags: gemma4 = vision/tools/thinking/audio; qwen3.6 = vision/tools/thinking; qwen3-coder = tools only; qwen2.5-coder = tools, 32K ctx.
- Demo pick: **gemma4:12b** (or hermes-gemma4:12b, which already has num_ctx 32k; not benchmarked). qwen3.6:27b needs ~17 GB + KV cache, likely CPU offload on a laptop -> slow. Measured latency: unknown (not run).
- SQL: qwen2.5-coder:7b is not installed, is ~1 yr old, and I found no current evidence it is "best small SQL". qwen3-coder:30b (19 GB, 3.3B active MoE) is fast per token but large and not installed. Recommendation: skip a separate coder model; give gemma4:12b the schema (DDL + sample values + 2-3 few-shot Q/SQL pairs) and `format` schema `{"sql": str}`. Evaluate on ~10 real questions before adding qwen2.5-coder:7b (4.7 GB pull).
- Never trust generated SQL: parse (e.g. sqlglot), allow a single SELECT only, add LIMIT, run with a read-only Snowflake role, retry once feeding the error back.

## 4. Gotchas
- **Tool calls as text**: Gemma 4 sometimes emits native `<|tool_call>` / Python-style calls in `content` with `tool_calls` empty (reports on vLLM/llama.cpp/Hermes; for Ollama, one report says /api/chat and /v1 return proper `tool_calls` and the failure was client-side, esp. streaming). Mitigations: Ollama >= 0.30.5 (models list it as required), few tools (4 is fine), short precise descriptions, `stream=False` for the router call, a fallback that regex-parses `{"name":..., "arguments":...}` from content, otherwise treat content as the final answer. Cap iterations (e.g. 5).
- **num_ctx**: default context is 4k when VRAM < 24 GiB (32k for 24-48 GiB); docs recommend >=64k for agents but memory scales. Truncation silently drops tool schemas/prompt. Set `options.num_ctx` (8-16k is plenty here) or `OLLAMA_CONTEXT_LENGTH`; changing it per request reloads the model, so keep it constant. Check `ollama ps` (CONTEXT, PROCESSOR = 100% GPU).
- **keep_alive**: default 5 min; pass `keep_alive="30m"` (or -1) on every call, or set `OLLAMA_KEEP_ALIVE`. Warm the model at app start.
- **Latency**: `think=False` for routing/SQL (thinking defaults ON); `temperature 0`; small `num_predict`; `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0` (halves KV memory, needs flash attn); `OLLAMA_NUM_PARALLEL=1`; keep system prompt/tools identical across turns so the prompt cache helps; return compact tool results; stream only the final answer to the UI.
- Tool results must be strings (`json.dumps`). Unknown tool name -> return an error string as the tool result, don't crash.

## Minimal agent loop
```python
import json, ollama   # pip install -U ollama
MODEL = "gemma4:12b"
OPTS = {"num_ctx": 16384, "temperature": 0}

def search_flights(origin: str, dest: str, date: str) -> str:
    """Search flights.
    Args:
      origin: IATA code
      dest: IATA code
      date: YYYY-MM-DD
    """
    return json.dumps([{"flight": "UA100", "dep": "08:00"}])  # stub
def track_flight(flight_number: str) -> str:
    """Live status of a flight.
    Args:
      flight_number: e.g. UA100
    """
    return json.dumps({"status": "delayed", "mins": 25})
def query_delay_history(flight_number: str, days: int = 30) -> str:
    """Historical delay stats (runs text-to-SQL on Snowflake).
    Args:
      flight_number: e.g. UA100
      days: lookback window
    """
    return json.dumps({"avg_delay_min": 14})
def watch_flight(flight_number: str) -> str:
    """Subscribe to alerts for a flight.
    Args:
      flight_number: e.g. UA100
    """
    return json.dumps({"watching": flight_number})

FUNCS = {f.__name__: f for f in (search_flights, track_flight, query_delay_history, watch_flight)}
SYSTEM = "You are a flight assistant. You may call several tools over several steps. Use tools for facts; answer briefly when done."

def run(user: str, max_steps: int = 5) -> str:
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    for _ in range(max_steps):
        r = ollama.chat(model=MODEL, messages=msgs, tools=list(FUNCS.values()),
                        think=False, stream=False, keep_alive="30m", options=OPTS)
        msgs.append(r.message)
        if not r.message.tool_calls:
            return r.message.content
        for tc in r.message.tool_calls:
            fn = FUNCS.get(tc.function.name)
            try:
                out = fn(**tc.function.arguments) if fn else f"error: unknown tool {tc.function.name}"
            except Exception as e:
                out = f"error: {e}"
            msgs.append({"role": "tool", "tool_name": tc.function.name, "content": str(out)})
    return "Stopped: step limit reached."

# Text-to-SQL step (separate call: format only, no tools)
from pydantic import BaseModel
class Sql(BaseModel):
    sql: str
def to_sql(question: str, ddl: str) -> str:
    r = ollama.chat(model=MODEL, think=False, keep_alive="30m", options=OPTS,
        messages=[{"role": "user", "content":
          f"Snowflake SQL. Schema:\n{ddl}\nOne SELECT only, with LIMIT. Question: {question}\n"
          f"Reply as JSON matching {Sql.model_json_schema()}"}],
        format=Sql.model_json_schema())
    return Sql.model_validate_json(r.message.content).sql  # validate read-only before executing
```

## Not verified
Actual latency/quality on this laptop; format+tools combined behavior; hermes-gemma4 vs base quality; SQL accuracy of any model; installed Ollama server version.

Sources: docs.ollama.com/capabilities/{tool-calling,structured-outputs,thinking}, docs.ollama.com/{api/chat,faq,context-length}, ollama.com/library/{gemma4,qwen3.6,qwen3-coder,qwen2.5-coder}, local `ollama show`; gemma4 text-tool-call reports: github.com/anomalyco/opencode/issues/20995, github.com/NousResearch/hermes-agent/issues/7457, github.com/ggml-org/llama.cpp/issues/22786.
