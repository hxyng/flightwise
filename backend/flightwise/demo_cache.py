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


def normalize(question: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", question.lower()).split())


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


def get_result(question: str) -> QueryResult | None:
    raw = _load().get("ask", {}).get(normalize(question))
    if not raw:
        return None
    r = QueryResult.model_validate(raw)
    r.answer = (r.answer or "") + CACHED_NOTE
    return r


def save_answer(question: str, text: str) -> None:
    if text.strip():
        _store("chat", normalize(question), {"text": text})


def get_answer(question: str) -> str | None:
    raw = _load().get("chat", {}).get(normalize(question))
    return (raw["text"] + CACHED_NOTE) if raw else None


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
