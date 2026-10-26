"""Autonomous tool-calling agent over the local Ollama model.

`run_agent` streams AgentEvents: thinking? -> (tool_call -> tool_result)* -> message -> done.
Other modules (providers, nl2sql, watcher) are imported lazily inside the tool functions so
this module imports even while they are still being built.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date as Date, datetime, timedelta
from typing import Any, AsyncIterator, Callable

from pydantic import BaseModel

from . import llm
from .models import AgentEvent

MAX_ITERS = 6           # LLM calls per user turn; the last one is made without tools
HISTORY_KEEP = 12       # messages returned in `done.history`
LIST_CAP = 5            # list items shown to the model per tool result
ROWS_CAP = 12           # nl2sql rows shown to the model
RISK_TOP_N = 8   # risk lookups are cheap SQL; score every offer


# --------------------------------------------------------------------------- tool schemas

def _fn(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props, "required": required}}}


_S = {"type": "string"}
TOOLS: list[dict] = [
    _fn("search_flights",
        "Search bookable flights between two airports on a date. Returns offers (price, times, stops) "
        "and, for the top offers, historical delay risk.",
        {"origin": {**_S, "description": "IATA airport code, e.g. OKC"},
         "destination": {**_S, "description": "IATA airport code, e.g. DEN"},
         "date": {**_S, "description": "YYYY-MM-DD"}},
        ["origin", "destination", "date"]),
    _fn("track_flight",
        "Live status of one flight (times, delay, gate, phase) plus its historical delay risk.",
        {"flight_number": {**_S, "description": "e.g. AA100"},
         "date": {**_S, "description": "YYYY-MM-DD, optional (default today)"}},
        ["flight_number"]),
    _fn("delay_risk",
        "Historical odds of a delay >= 15 min for a carrier departing an airport, optionally at an hour.",
        {"carrier": {**_S, "description": "2-letter airline code, e.g. AA"},
         "origin": {**_S, "description": "IATA airport code"},
         "hour": {"type": "integer", "description": "departure hour 0-23, optional"}},
        ["carrier", "origin"]),
    _fn("query_delay_history",
        "Answer a question about US on-time history (BTS data) with SQL, e.g. "
        "'Which airline is most on time from OKC?'.",
        {"question": {**_S, "description": "the question in plain English"}},
        ["question"]),
    _fn("watch_flight",
        "Keep watching a flight in the background and push updates on delays, gate or status changes.",
        {"flight_number": {**_S, "description": "e.g. AA100"},
         "date": {**_S, "description": "YYYY-MM-DD, optional (default today)"}},
        ["flight_number"]),
    _fn("list_watched", "List the flights currently being watched.", {}, []),
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


# --------------------------------------------------------------------------- dates

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _today() -> Date:
    return datetime.now().date()


def resolve_date(value: str | None, today: Date | None = None) -> str | None:
    """'tomorrow', 'Friday', 'next fri', '10/30', '2026-10-30' -> 'YYYY-MM-DD'. Unknown text passes through."""
    if value is None:
        return None
    today = today or _today()
    s = str(value).strip().lower()
    if not s:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    if s in ("today", "tonight", "now"):
        return today.isoformat()
    if s == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if s in ("day after tomorrow", "the day after tomorrow"):
        return (today + timedelta(days=2)).isoformat()
    m = re.fullmatch(r"(?:(next|this)\s+)?([a-z]+)", s)
    if m:
        name = m.group(2)
        for i, wd in enumerate(_WEEKDAYS):
            if len(name) >= 3 and wd.startswith(name):
                ahead = (i - today.weekday()) % 7
                if m.group(1) == "next" and ahead == 0:
                    ahead = 7
                return (today + timedelta(days=ahead)).isoformat()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        if y < 100:
            y += 2000
        try:
            out = Date(y, mo, d)
        except ValueError:
            return value
        if not m.group(3) and out < today:
            out = Date(y + 1, mo, d)
        return out.isoformat()
    return value


def _date_context(today: Date) -> str:
    days = [today + timedelta(days=i) for i in range(8)]
    return ", ".join(f"{d.strftime('%a')} {d.isoformat()}" for d in days)


def system_prompt(today: Date | None = None) -> str:
    today = today or _today()
    return f"""You are FlightWise, a proactive flight assistant. Today is {today.strftime('%A')} {today.isoformat()}.
Next days: {_date_context(today)}. Always pass dates to tools as YYYY-MM-DD.

Use tools for every fact; never invent flight times, prices or percentages. Chain tools on your own:
- "track/status of <flight>": call track_flight (it already includes delay risk). If the user wants to be kept
  updated or notified, also call watch_flight; otherwise offer to watch it in one line.
- "find a flight A to B <day>": call search_flights. Offers come with delay risk, and the best balance of
  reliability, price and stops is marked "recommended": true with a "why". Recommend that offer and give its why;
  mention the cheapest as an alternative if different. Risk label "unknown" means too little history.
- Questions about history/trends (which airline, which airport, which month): call query_delay_history.
- "what am I watching": call list_watched.
Quote times from the *_local fields (raw ISO times are UTC). If delay risk shows an error, say history is
unavailable rather than calling the flight low-risk.
Answer in short markdown, under ~100 words (a few bullets or a 3-row table) with concrete numbers from tool results only.
If a tool returns an error, say so briefly and continue with what you have."""


# --------------------------------------------------------------------------- tool backends

def _dump(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, (list, tuple)):
        return [_dump(o) for o in obj]
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items()}
    return obj


def _carrier_of(status: dict) -> str:
    code = status.get("airline_code")
    if code:
        return code
    m = re.match(r"([A-Z0-9]{2})", str(status.get("flight_number", "")).upper())
    return m.group(1) if m else ""


_TZ_AIRPORTS = {
    "America/New_York": "ATL BOS BWI CLT CVG DCA DTW EWR FLL IAD JAX JFK LGA MCO MIA PBI PHL PIT RDU RSW TPA CLE CMH IND BUF RIC ORF SAV CHS",
    "America/Chicago": "ORD MDW DFW DAL IAH HOU MSP STL MCI MSY AUS SAT BNA MEM MKE OKC TUL OMA DSM LIT BHM ICT",
    "America/Denver": "DEN SLC ABQ BOI ELP COS",
    "America/Phoenix": "PHX TUS",
    "America/Los_Angeles": "LAX SFO SEA SAN SJC OAK SMF PDX LAS SNA BUR ONT RNO",
    "America/Anchorage": "ANC", "Pacific/Honolulu": "HNL OGG KOA LIH",
}
AIRPORT_TZ = {a: tz for tz, codes in _TZ_AIRPORTS.items() for a in codes.split()}


def _local_dt(iso: Any, airport: str | None) -> datetime | None:
    """Parse an ISO time and move it to the airport's local zone (BTS hours are local)."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    tz = AIRPORT_TZ.get((airport or "").upper())
    if dt.tzinfo is not None and tz:
        from zoneinfo import ZoneInfo
        dt = dt.astimezone(ZoneInfo(tz))
    elif dt.tzinfo is not None and dt.utcoffset() == timedelta(0):
        return None   # UTC at an airport we can't place: hour would be wrong
    return dt


def _hour_of(iso: Any, airport: str | None = None) -> int | None:
    dt = _local_dt(iso, airport)
    return dt.hour if dt else None


def _local_str(iso: Any, airport: str | None) -> str | None:
    dt = _local_dt(iso, airport)
    return dt.strftime("%a %H:%M local") if dt else None


async def _risk(carrier: str, origin: str, hour: int | None) -> dict:
    from .data import nl2sql
    return _dump(await asyncio.to_thread(nl2sql.delay_risk, carrier, origin, hour))


async def _safe_risk(carrier: str, origin: str, hour: int | None) -> dict:
    try:
        return await _risk(carrier, origin, hour)
    except Exception as e:  # noqa: BLE001 - risk is optional enrichment
        return {"error": f"delay history unavailable ({type(e).__name__})"}


async def t_search_flights(origin: str, destination: str, date: str) -> Any:
    from .providers import search
    offers = _dump(await search.search_flights(origin.upper(), destination.upper(), resolve_date(date)))
    for i, o in enumerate(offers):
        o["departure_local"] = _local_str(o.get("departure"), o.get("origin"))
        o["arrival_local"] = _local_str(o.get("arrival"), o.get("destination"))
        if i < RISK_TOP_N:
            carrier = o.get("airline_code") or _carrier_of({"flight_number": (o.get("flight_numbers") or [""])[0]})
            o["risk"] = await _safe_risk(carrier, o["origin"], _hour_of(o.get("departure"), o["origin"]))
    _mark_recommended(offers)
    return offers


def _offer_score(o: dict) -> float | None:
    """Lower is better: % delayed >= 15 min, plus $10 ~ 1 point and 10 points per stop.
    Offers without known delay history can't be recommended."""
    risk = o.get("risk") or {}
    if risk.get("label") in (None, "unknown") or risk.get("pct_delayed_15") is None:
        return None
    return risk["pct_delayed_15"] + (o.get("price") or 0) / 10 + 10 * (o.get("stops") or 0)


def _mark_recommended(offers: list[dict]) -> None:
    """Pick the recommendation in code, not in the model, so it's deterministic and explainable."""
    scored = [(sc, o) for o in offers if (sc := _offer_score(o)) is not None]
    if scored:
        best = min(scored, key=lambda t: t[0])[1]
        best["recommended"] = True
        best["why"] = (f"{best['risk']['pct_delayed_15']:.0f}% of similar flights delayed 15+ min, "
                       f"${best.get('price') or 0:.0f}, {best.get('stops', 0)} stop(s)")
        offers.insert(0, offers.pop(offers.index(best)))   # the model only sees the first few offers


async def t_track_flight(flight_number: str, date: str | None = None) -> Any:
    from .providers import status as status_mod
    st = _dump(await status_mod.get_flight_status(flight_number, resolve_date(date)))
    st["departure_local"] = _local_str(st.get("estimated_departure") or st.get("scheduled_departure"), st["origin"])
    st["arrival_local"] = _local_str(st.get("estimated_arrival") or st.get("scheduled_arrival"), st["destination"])
    risk = await _safe_risk(_carrier_of(st), st["origin"], _hour_of(st.get("scheduled_departure"), st["origin"]))
    return {"status": st, "risk": risk}


async def t_delay_risk(carrier: str, origin: str, hour: int | None = None) -> Any:
    h = int(hour) if hour not in (None, "") else None
    return await _risk(carrier.upper(), origin.upper(), h)


async def t_query_delay_history(question: str) -> Any:
    from .data import nl2sql
    return _dump(await asyncio.to_thread(nl2sql.ask, question, False))


async def t_watch_flight(flight_number: str, date: str | None = None) -> Any:
    from .watcher import watcher
    return _dump(await watcher.add(flight_number, resolve_date(date)))


async def t_list_watched() -> Any:
    from .watcher import watcher
    return _dump(watcher.list())


FUNCS: dict[str, Callable[..., Any]] = {
    "search_flights": t_search_flights, "track_flight": t_track_flight, "delay_risk": t_delay_risk,
    "query_delay_history": t_query_delay_history, "watch_flight": t_watch_flight,
    "list_watched": t_list_watched,
}


async def call_tool(name: str, args: dict | None) -> tuple[Any, bool]:
    """Run one tool. Returns (JSON-able result, ok). Never raises."""
    fn = FUNCS.get(name)
    if fn is None:
        return f"error: unknown tool '{name}'. Available: {', '.join(sorted(FUNCS))}", False
    args = dict(args or {})
    if "date" in args:
        args["date"] = resolve_date(args["date"])
    try:
        return await fn(**args), True
    except TypeError as e:
        return f"error: bad arguments for {name}: {e}", False
    except Exception as e:  # noqa: BLE001 - a tool failure becomes a tool result
        return f"error: {name} failed: {type(e).__name__}: {e}", False


# --------------------------------------------------------------------------- compaction for the model

_DROP_KEYS = {"sql", "source", "updated_at", "created_at", "id", "progress", "chart", "backend"}


def compact(obj: Any, _depth: int = 0) -> Any:
    """Smaller copy for the model: drop nulls/noise keys, cap lists, round floats."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if v is None or v == [] or v == {} or k in _DROP_KEYS:
                continue
            cap = ROWS_CAP if k == "rows" else LIST_CAP
            out[k] = compact(v[:cap] if isinstance(v, list) else v, _depth + 1)
            if isinstance(v, list) and len(v) > cap:
                out[f"{k}_total"] = len(v)
        return out
    if isinstance(obj, list):
        items = [compact(o, _depth + 1) for o in obj[:LIST_CAP if _depth == 0 else ROWS_CAP]]
        return items
    if isinstance(obj, float):
        return round(obj, 1)
    return obj


def to_model_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list) and len(result) > LIST_CAP:
        return json.dumps({"items": compact(result), "total": len(result)}, separators=(",", ":"), default=str)
    return json.dumps(compact(result), separators=(",", ":"), default=str)


# --------------------------------------------------------------------------- text tool-call fallback

_GEMMA_CALL = re.compile(r"call:\s*([a-z_]+)\s*\{(.*?)\}", re.S)
_GEMMA_ARG = re.compile(r'([a-zA-Z_]+)\s*:\s*(?:<\|"\|>(.*?)<\|"\|>|"([^"]*)"|([^,}]+))', re.S)
_PY_CALL = re.compile(r"\b(" + "|".join(sorted(TOOL_NAMES)) + r")\s*\(([^()]*)\)")
_PY_ARG = re.compile(r"""([a-zA-Z_]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^,\s)]+))""")


def _coerce(v: str) -> Any:
    v = v.strip()
    return int(v) if re.fullmatch(r"-?\d+", v) else v


def parse_text_tool_calls(content: str | None) -> list[dict]:
    """Recover tool calls the model wrote as text. Returns ollama-shaped tool_calls (maybe empty)."""
    if not content:
        return []
    calls: list[dict] = []
    # 1) JSON objects: {"name": ..., "arguments"|"parameters": {...}}
    dec = json.JSONDecoder()
    i = 0
    while (i := content.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(content, i)
        except json.JSONDecodeError:
            i += 1
            continue
        objs = obj if isinstance(obj, list) else [obj]
        for o in objs:
            if isinstance(o, dict) and isinstance(o.get("function"), dict):
                o = o["function"]
            if isinstance(o, dict) and o.get("name") in TOOL_NAMES:
                args = o.get("arguments", o.get("parameters", {}))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                calls.append({"function": {"name": o["name"], "arguments": args or {}}})
        i = end
    if calls:
        return calls
    # 2) Gemma native: <|tool_call>call:name{key:<|"|>value<|"|>}<tool_call|>
    for name, body in _GEMMA_CALL.findall(content):
        if name in TOOL_NAMES:
            args = {k: _coerce(a or b or c) for k, a, b, c in _GEMMA_ARG.findall(body)}
            calls.append({"function": {"name": name, "arguments": args}})
    if calls:
        return calls
    # 3) Python style: track_flight(flight_number="AA100")
    for name, body in _PY_CALL.findall(content):
        args = {k: _coerce(a or b or c) for k, a, b, c in _PY_ARG.findall(body)}
        calls.append({"function": {"name": name, "arguments": args}})
    return calls


# --------------------------------------------------------------------------- loop

def _trim_history(msgs: list[dict]) -> list[dict]:
    out = [m for m in msgs if m.get("role") != "system"][-HISTORY_KEEP:]
    while out and out[0].get("role") != "user":   # never start on an orphan tool result
        out.pop(0)
    return out


def _event(type_: str, **data: Any) -> AgentEvent:
    return AgentEvent(type=type_, data=data)


STREAM = True   # stream answer tokens to the UI as "delta" events; tests turn it off
_CALL_START = re.compile(r"^\s*(\{|`|\[|call:|(" + "|".join(FUNCS) + r")\s*\()")


async def _model_turn(msgs: list[dict], tools: list[dict] | None) -> AsyncIterator[AgentEvent | dict]:
    """One model turn. Yields "delta" AgentEvents while text streams, then the assembled
    assistant message dict last. Text that looks like a hand-written tool call isn't streamed."""
    if not STREAM:
        yield await asyncio.to_thread(llm.chat, msgs, tools)
        return
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def pump() -> None:
        try:
            for chunk in llm.chat_stream(msgs, tools):
                loop.call_soon_threadsafe(q.put_nowait, chunk)
            loop.call_soon_threadsafe(q.put_nowait, None)
        except Exception as e:  # noqa: BLE001
            loop.call_soon_threadsafe(q.put_nowait, e)

    task = loop.run_in_executor(None, pump)
    content, thinking, calls = "", "", []
    streaming: bool | None = None          # undecided until we see enough text
    while (chunk := await q.get()) is not None:
        if isinstance(chunk, Exception):
            raise chunk
        thinking += chunk.get("thinking") or ""
        calls += chunk.get("tool_calls") or []
        piece = chunk.get("content") or ""
        if not piece:
            continue
        content += piece
        if streaming is None and (len(content.strip()) >= 8 or _CALL_START.match(content)):
            streaming = not _CALL_START.match(content)
            piece = content if streaming else ""
        if streaming:
            yield _event("delta", text=piece)
    await task
    reply = {"role": "assistant", "content": content, "thinking": thinking or None}
    if calls:
        reply["tool_calls"] = calls
    yield reply


async def run_agent(message: str, history: list[dict] | None = None) -> AsyncIterator[AgentEvent]:
    msgs: list[dict] = [{"role": "system", "content": system_prompt()}]
    msgs += [m for m in (history or []) if m.get("role") != "system"]
    msgs.append({"role": "user", "content": message})

    final_text: str | None = None
    failed = False
    for it in range(MAX_ITERS):
        last = it == MAX_ITERS - 1
        try:
            reply: dict = {}
            async for out in _model_turn(msgs, None if last else TOOLS):
                if isinstance(out, AgentEvent):
                    yield out
                else:
                    reply = out
        except Exception as e:  # noqa: BLE001
            yield _event("error", text=f"Model call failed: {type(e).__name__}: {e}")
            failed = True
            break
        if reply.get("thinking"):
            yield _event("thinking", text=reply["thinking"])
        content = reply.get("content") or ""
        tool_calls = reply.get("tool_calls") or []
        if not tool_calls and not last:
            tool_calls = parse_text_tool_calls(content)
            if tool_calls:
                content = ""   # it was a call, not an answer
        if last or not tool_calls:
            final_text = content.strip() or None
            if final_text:
                msgs.append({"role": "assistant", "content": final_text})
            break

        msgs.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            yield _event("tool_call", name=name, arguments=args)
            result, ok = await call_tool(name, args)
            yield _event("tool_result", name=name, result=result, ok=ok)
            msgs.append({"role": "tool", "tool_name": name, "content": to_model_text(result)})

    if final_text is None and not failed:
        final_text = "I couldn't finish that within my step limit. Try a more specific question."
        msgs.append({"role": "assistant", "content": final_text})
    if final_text:
        yield _event("message", text=final_text)
    yield _event("done", history=_trim_history(msgs))
