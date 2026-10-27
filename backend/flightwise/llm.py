"""Thin client for a local Ollama model. The only module that talks to the LLM."""
from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Iterator

import httpx

from . import config

log = logging.getLogger(__name__)
STATS: deque[dict] = deque(maxlen=200)   # per-call timings, newest last (read by scripts/bench_speed.py)

OPTIONS = {"num_ctx": 16384, "temperature": 0, "num_predict": 400}   # keep constant: changing num_ctx reloads the model
_client = httpx.Client(base_url=config.OLLAMA_URL, timeout=180)


def chat(messages: list[dict], tools: list[dict] | None = None,
         format: dict | str | None = None, think: bool = False) -> dict:
    """One non-streaming /api/chat call. Returns the assistant `message` dict
    ({"role", "content", "thinking"?, "tool_calls"?}). Don't combine tools and format."""
    body: dict[str, Any] = {
        "model": config.OLLAMA_MODEL, "messages": messages, "stream": False,
        "think": think, "keep_alive": "30m", "options": OPTIONS,
    }
    if tools:
        body["tools"] = tools
    if format:
        body["format"] = format
    r = _client.post("/api/chat", json=body)
    r.raise_for_status()
    data = r.json()
    _record(data, "agent" if tools else "sql" if format else "text")
    return data["message"]


def chat_stream(messages: list[dict], tools: list[dict] | None = None,
                think: bool = False, max_tokens: int | None = None) -> Iterator[dict]:
    """Streaming /api/chat. Yields each chunk's `message` dict; content arrives piece by
    piece, tool_calls usually in one chunk near the end. `max_tokens` caps this call only
    (num_predict doesn't reload the model or touch the prompt cache)."""
    options = {**OPTIONS, "num_predict": max_tokens} if max_tokens else OPTIONS
    body: dict[str, Any] = {
        "model": config.OLLAMA_MODEL, "messages": messages, "stream": True,
        "think": think, "keep_alive": "30m", "options": options,
    }
    if tools:
        body["tools"] = tools
    with _client.stream("POST", "/api/chat", json=body) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line:
                chunk = json.loads(line)
                if chunk.get("done"):
                    _record(chunk, "agent-stream")
                yield chunk.get("message", {})


def _record(resp: dict, label: str) -> None:
    """Keep and log Ollama's timing fields for one call (durations are nanoseconds)."""
    ns = 1e9
    st = {
        "label": label,
        "prompt_tokens": resp.get("prompt_eval_count", 0),
        "cached_tokens": resp.get("prompt_eval_cached_count", 0),
        "prefill_s": round(resp.get("prompt_eval_duration", 0) / ns, 2),
        "output_tokens": resp.get("eval_count", 0),
        "decode_s": round(resp.get("eval_duration", 0) / ns, 2),
        "total_s": round(resp.get("total_duration", 0) / ns, 2),
    }
    STATS.append(st)
    log.info("llm %(label)s: prompt %(prompt_tokens)s (cached %(cached_tokens)s) in %(prefill_s)ss, "
             "output %(output_tokens)s in %(decode_s)ss, total %(total_s)ss", st)


def chat_json(messages: list[dict], schema: dict) -> dict:
    """Structured output: returns the parsed JSON object matching `schema`."""
    return json.loads(chat(messages, format=schema)["content"])


def health() -> bool:
    try:
        return _client.get("/api/tags", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


def warm() -> None:
    """Load the model into memory so the first demo question isn't slow."""
    try:
        chat([{"role": "user", "content": "hi"}])
    except httpx.HTTPError:
        pass
