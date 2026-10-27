"""Deterministic answer text for tool results the agent already has.

The model still decides which tools to call; these functions only turn the results into the
facts the user reads, so every number is exact and the model doesn't spend ~150 tokens
re-typing them. `render` returns None when any result isn't covered, and the agent then
falls back to a normal model-written answer.
"""
from __future__ import annotations

import re
from typing import Any

WATCH_CUE = re.compile(r"\b(keep me|posted|notify|notification|updates?|alert|watch)\b", re.I)


def _pct(v: Any) -> str:
    return f"{float(v):.0f}%" if v is not None else "?"


def _risk_line(risk: dict | None) -> str:
    if not risk or risk.get("error"):
        return "Delay history isn't available for this flight."
    if risk.get("label") == "unknown":
        return "There's too little history to rate its delay risk."
    return (f"Historical delay risk: **{risk['label']}**. {_pct(risk.get('pct_delayed_15'))} of "
            f"{int(risk.get('flights') or 0):,} similar flights left 15+ min late.")


def _status(res: dict) -> str | None:
    st = res.get("status") if isinstance(res, dict) else None
    if not isinstance(st, dict) or not st.get("flight_number"):
        return None
    phase = str(st.get("status") or "unknown").replace("_", " ")
    head = f"**{st['flight_number']}**"
    if st.get("airline"):
        head += f" ({st['airline']})"
    head += f" {st.get('origin', '?')} → {st.get('destination', '?')}: **{phase.capitalize()}**"
    bits = []
    if st.get("departure_local"):
        bits.append(f"departs {st['departure_local']}")
    if st.get("gate"):
        bits.append(f"gate {st['gate']}")
    delay = st.get("departure_delay_min") or 0
    bits.append(f"delayed {delay} min" if delay >= 5 else "on time")
    return f"{head}, " + ", ".join(bits) + ".\n\n" + _risk_line(res.get("risk"))


def _offer_name(o: dict) -> str:
    nums = "/".join(o.get("flight_numbers") or [])
    return f"{o.get('airline', '?')} {nums}".strip()


def _offers(offers: Any) -> str | None:
    if not isinstance(offers, list):
        return None
    if not offers:
        return "I didn't find any flights for that route and date."
    if not all(isinstance(o, dict) and "price" in o for o in offers):
        return None
    cheapest = min(offers, key=lambda o: o.get("price") if o.get("price") is not None else float("inf"))
    pick = next((o for o in offers if o.get("recommended")), None)
    stops = lambda o: "nonstop" if not o.get("stops") else f"{o['stops']} stop"  # noqa: E731
    lines = [f"Found {len(offers)} flights."]
    if pick:
        lines.append(f"**Agent pick: {_offer_name(pick)}**, {pick.get('departure_local') or ''}, "
                     f"${pick.get('price', 0):.0f}, {stops(pick)}. Why: {pick.get('why', 'best balance')}.")
    else:
        lines.append("None of them has enough delay history to recommend on reliability.")
    if cheapest is not pick:
        risk = cheapest.get("risk") or {}
        rating = (f"{risk['label']} risk, {_pct(risk.get('pct_delayed_15'))} delayed"
                  if risk.get("label") not in (None, "unknown") else "no delay history")
        lines.append(f"Cheapest: {_offer_name(cheapest)} at ${cheapest.get('price', 0):.0f} ({rating}).")
    return "\n\n".join(lines)


def _risk(res: Any) -> str | None:
    if not isinstance(res, dict) or "label" not in res:
        return None
    where = f"{res.get('carrier', '?')} from {res.get('origin', '?')}"
    if res.get("hour") is not None:
        h = int(res["hour"])
        where += f" around {h % 12 or 12} {'AM' if h < 12 else 'PM'}"
    return f"{where}. {_risk_line(res)}"


def _watch(res: Any) -> str | None:
    if not isinstance(res, dict) or not res.get("flight_number"):
        return None
    return f"I'm watching **{res['flight_number']}** and will post gate, delay and status changes here."


def _watchlist(res: Any) -> str | None:
    if not isinstance(res, list):
        return None
    if not res:
        return "You're not watching any flights yet."
    names = []
    for w in res:
        st = (w.get("last_status") or {}).get("status") if isinstance(w, dict) else None
        names.append(f"{w.get('flight_number', '?')}" + (f" ({str(st).replace('_', ' ')})" if st else ""))
    return "Watching: " + ", ".join(names) + "."


def _history(res: Any) -> str | None:
    if not isinstance(res, dict) or res.get("error") or not res.get("columns"):
        return None
    import pandas as pd

    from .data.summary import template_explain
    return template_explain(pd.DataFrame(res.get("rows") or [], columns=res["columns"]))


RENDERERS = {
    "track_flight": _status, "search_flights": _offers, "delay_risk": _risk,
    "watch_flight": _watch, "list_watched": _watchlist, "query_delay_history": _history,
}


def render(message: str, results: list[tuple[str, Any, bool]]) -> str | None:
    """Answer text for this turn's (tool name, result, ok) list, or None to let the model answer."""
    if not results or not all(ok for _, _, ok in results):
        return None
    names = {n for n, _, _ in results}
    if WATCH_CUE.search(message) and "track_flight" in names and "watch_flight" not in names:
        return None   # the user asked to be kept posted; let the model call watch_flight first
    parts = []
    for name, result, _ in results:
        fn = RENDERERS.get(name)
        text = fn(result) if fn else None
        if text is None:
            return None
        parts.append(text)
    return "\n\n".join(parts)


SENTENCE_PROMPT = ("The user is already shown this summary of the tool results:\n\n{summary}\n\n"
                   "Reply with ONE short sentence of practical advice for them (max 25 words). "
                   "Don't repeat the summary or add numbers that aren't in it.")
