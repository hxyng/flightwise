"""Wi-Fi backup: remember good answers, serve them when the LLM or DB is down."""
from __future__ import annotations

import json
import re
import sys
import threading

from . import config
from .models import QueryResult

CACHED_NOTE = "\n\n_(cached answer: offline mode)_"
DEMO_QUESTIONS = [
    "When's the best time to fly out of OKC?",
    "Which airline is most reliable?",
    "Which day of the week has the worst delays?",
    "What are the worst routes for delays?",
    "How do cancellations change by month?",
]
_lock = threading.Lock()


_FILLER = {"please", "hey", "hi", "flightwise", "can", "could", "you", "tell", "me", "show", "i", "want", "to", "know"}
# Answers that only depend on the historical BTS data: safe to serve before asking the model.
STATIC_TOOLS = {"query_delay_history", "delay_risk"}


def normalize(question: str) -> str:
    words = re.sub(r"[^a-z0-9 ]+", " ", question.lower()).split()
    return " ".join(w for w in words if w not in _FILLER) or " ".join(words)


def _load() -> dict:
    try:
        d = json.loads(config.DEMO_CACHE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _store(section: str, key: str, value: dict) -> None:
    with _lock:
        d = _load()
        d.setdefault(section, {})[key] = value
        config.DEMO_CACHE.parent.mkdir(parents=True, exist_ok=True)
        config.DEMO_CACHE.write_text(json.dumps(d, indent=2, default=str), encoding="utf-8")


def save_result(question: str, result: QueryResult) -> None:
    if result.error or not result.rows:
        return
    _store("ask", normalize(question), result.model_dump(mode="json"))


def _lookup(section: str, question: str) -> dict | None:
    """Find a saved entry. Keys saved before filler words were dropped from `normalize` still
    match, because normalizing an old key gives the same string as normalizing the question."""
    entries = _load().get(section, {})
    key = normalize(question)
    if key in entries:
        return entries[key]
    return next((v for k, v in entries.items() if normalize(k) == key), None)


def get_result(question: str, offline: bool = True) -> QueryResult | None:
    """Saved answer for a data question. `offline` adds the offline-mode note (fallback path).
    The summary is re-rendered from the saved rows, so old wording never comes back."""
    raw = _lookup("ask", question)
    if not raw:
        return None
    r = QueryResult.model_validate(raw)
    try:
        import pandas as pd

        from .data.summary import template_explain
        r.answer = template_explain(pd.DataFrame(r.rows, columns=r.columns)) or r.answer
    except Exception:  # noqa: BLE001 - keep the saved answer if re-rendering fails
        pass
    if offline:
        r.answer = (r.answer or "") + CACHED_NOTE
    return r


def save_answer(question: str, text: str, tools: set[str] | None = None) -> None:
    if text.strip():
        static = bool(tools) and tools <= STATIC_TOOLS
        _store("chat", normalize(question), {"text": text, "static": static})


def get_answer(question: str, static_only: bool = False) -> str | None:
    """Saved agent answer. With `static_only`, only answers built purely from historical data
    (never live flight status or prices, which go stale) and without the offline note."""
    raw = _lookup("chat", question)
    if not raw:
        return None
    if static_only:
        return raw["text"] if raw.get("static") else None
    return raw["text"] + CACHED_NOTE


def warm() -> int:
    from .data import nl2sql
    ok = 0
    for q in DEMO_QUESTIONS:
        try:
            r = nl2sql.ask(q)
            if r.error or not r.rows:
                print(f"FAIL  {q}: {r.error or 'no rows'}")
                continue
            save_result(q, r)
            ok += 1
            print(f"OK    {q}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {q}: {e}")
    print(f"cached {ok}/{len(DEMO_QUESTIONS)} -> {config.DEMO_CACHE}")
    return ok


if __name__ == "__main__":
    if sys.argv[1:] == ["warm"]:
        sys.exit(0 if warm() == len(DEMO_QUESTIONS) else 1)
    print("usage: python -m flightwise.demo_cache warm")
    sys.exit(2)
