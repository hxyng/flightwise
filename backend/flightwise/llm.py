"""Thin client for a local Ollama model. The only module that talks to the LLM."""
from __future__ import annotations

import json
from typing import Any, Iterator

import httpx

from . import config

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
    return r.json()["message"]


def chat_stream(messages: list[dict], tools: list[dict] | None = None,
                think: bool = False) -> Iterator[dict]:
    """Streaming /api/chat. Yields each chunk's `message` dict; content arrives piece by
    piece, tool_calls usually in one chunk near the end."""
    body: dict[str, Any] = {
        "model": config.OLLAMA_MODEL, "messages": messages, "stream": True,
        "think": think, "keep_alive": "30m", "options": OPTIONS,
    }
    if tools:
        body["tools"] = tools
    with _client.stream("POST", "/api/chat", json=body) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line:
                yield json.loads(line).get("message", {})


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
