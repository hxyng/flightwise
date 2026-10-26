import asyncio
import json
from datetime import date

import pytest

from flightwise import agent


def run(message, history=None):
    async def go():
        return [e async for e in agent.run_agent(message, history)]
    return asyncio.run(go())


class FakeLLM:
    """Scripted llm.chat: returns replies in order, records what it was sent."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, messages, tools=None, format=None, think=False):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        r = self.replies.pop(0) if self.replies else {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "list_watched", "arguments": {}}}]}
        return {"role": "assistant", **r}


@pytest.fixture
def fake_tools(monkeypatch):
    seen = []

    async def track(flight_number, date=None):
        seen.append(("track_flight", flight_number, date))
        return {"status": {"flight_number": flight_number, "status": "delayed", "departure_delay_min": 25,
                           "origin": "OKC", "sql": "SELECT 1", "gate": None},
                "risk": {"carrier": "AA", "origin": "OKC", "pct_delayed_15": 21.456, "label": "medium"}}

    async def watch(flight_number, date=None):
        seen.append(("watch_flight", flight_number, date))
        return {"id": "w1", "flight_number": flight_number, "date": date or "2026-10-26"}

    async def boom():
        raise RuntimeError("db down")

    monkeypatch.setitem(agent.FUNCS, "track_flight", track)
    monkeypatch.setitem(agent.FUNCS, "watch_flight", watch)
    monkeypatch.setitem(agent.FUNCS, "list_watched", boom)
    return seen


def tc(name, **args):
    return {"function": {"name": name, "arguments": args}}


def types(events):
    return [e.type for e in events]


def test_tool_call_then_answer(monkeypatch, fake_tools):
    fake = FakeLLM([
        {"content": "", "tool_calls": [tc("track_flight", flight_number="AA100")]},
        {"content": "", "thinking": "user wants updates", "tool_calls": [tc("watch_flight", flight_number="AA100", date="tomorrow")]},
        {"content": "**AA100** is delayed 25 min; 21% of flights delay. Watching it."},
    ])
    monkeypatch.setattr(agent.llm, "chat", fake)
    ev = run("track AA100 and keep me posted")
    assert types(ev) == ["tool_call", "tool_result", "thinking", "tool_call", "tool_result", "message", "done"]
    assert ev[0].data == {"name": "track_flight", "arguments": {"flight_number": "AA100"}}
    # UI gets the full result, the model gets a compact string
    assert ev[1].data["result"]["status"]["sql"] == "SELECT 1"
    tool_msg = fake.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_name"] == "track_flight"
    payload = json.loads(tool_msg["content"])
    assert "sql" not in payload["status"] and "gate" not in payload["status"]
    assert payload["risk"]["pct_delayed_15"] == 21.5
    # relative date resolved before hitting the backend
    assert fake_tools[1][2] == agent.resolve_date("tomorrow")
    assert ev[-2].data["text"].startswith("**AA100**")
    hist = ev[-1].data["history"]
    assert hist[0] == {"role": "user", "content": "track AA100 and keep me posted"}
    assert all(m["role"] != "system" for m in hist)
    # system prompt carries today's date and tools are sent
    sys = fake.calls[0]["messages"][0]
    assert sys["role"] == "system" and date.today().isoformat() in sys["content"]
    assert fake.calls[0]["tools"] is agent.TOOLS


def test_text_fallback_json(monkeypatch, fake_tools):
    fake = FakeLLM([
        {"content": 'Sure!\n```json\n{"name": "track_flight", "arguments": {"flight_number": "UA9"}}\n```'},
        {"content": "UA9 is delayed."},
    ])
    monkeypatch.setattr(agent.llm, "chat", fake)
    ev = run("status UA9")
    assert types(ev) == ["tool_call", "tool_result", "message", "done"]
    assert ev[0].data["arguments"] == {"flight_number": "UA9"}
    assert fake.calls[1]["messages"][-2]["tool_calls"][0]["function"]["name"] == "track_flight"


@pytest.mark.parametrize("text,name,args", [
    ('<|tool_call>call:track_flight{flight_number:<|"|>DL5<|"|>}<tool_call|>', "track_flight", {"flight_number": "DL5"}),
    ('track_flight(flight_number="WN12", date="2026-11-01")', "track_flight",
     {"flight_number": "WN12", "date": "2026-11-01"}),
    ('{"function": {"name": "delay_risk", "parameters": {"carrier": "AA", "origin": "OKC", "hour": 7}}}',
     "delay_risk", {"carrier": "AA", "origin": "OKC", "hour": 7}),
])
def test_parse_text_variants(text, name, args):
    calls = agent.parse_text_tool_calls(text)
    assert calls == [{"function": {"name": name, "arguments": args}}]


def test_plain_text_is_not_a_call():
    assert agent.parse_text_tool_calls('Your flight {is} on time. {"a": 1}') == []


def test_unknown_tool_and_exception(monkeypatch, fake_tools):
    fake = FakeLLM([
        {"content": "", "tool_calls": [tc("book_hotel", city="DEN"), tc("list_watched")]},
        {"content": "Sorry, couldn't do that."},
    ])
    monkeypatch.setattr(agent.llm, "chat", fake)
    ev = run("book me a hotel")
    assert types(ev) == ["tool_call", "tool_result", "tool_call", "tool_result", "message", "done"]
    assert ev[1].data["ok"] is False and "unknown tool" in ev[1].data["result"]
    assert ev[3].data["ok"] is False and "db down" in ev[3].data["result"]
    tool_msgs = [m for m in fake.calls[1]["messages"] if m["role"] == "tool"]
    assert [m["tool_name"] for m in tool_msgs] == ["book_hotel", "list_watched"]


def test_bad_arguments(monkeypatch, fake_tools):
    fake = FakeLLM([{"content": "", "tool_calls": [tc("track_flight", flight="AA1")]}, {"content": "ok"}])
    monkeypatch.setattr(agent.llm, "chat", fake)
    ev = run("x")
    assert "bad arguments" in ev[1].data["result"]


def test_iteration_cap(monkeypatch, fake_tools):
    fake = FakeLLM([])   # always asks for a tool
    monkeypatch.setattr(agent.llm, "chat", fake)
    ev = run("loop forever")
    assert len(fake.calls) == agent.MAX_ITERS
    assert fake.calls[-1]["tools"] is None           # last call forced to answer without tools
    assert types(ev).count("tool_call") == agent.MAX_ITERS - 1
    assert ev[-2].type == "message" and "step limit" in ev[-2].data["text"]
    assert ev[-1].type == "done"


def test_llm_failure_emits_error(monkeypatch):
    def broken(*a, **k):
        raise ConnectionError("ollama not running")
    monkeypatch.setattr(agent.llm, "chat", broken)
    ev = run("hi")
    assert types(ev) == ["error", "done"]
    assert "ollama not running" in ev[0].data["text"]


def test_history_passed_and_trimmed(monkeypatch):
    old = []
    for i in range(10):
        old += [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"}]
    fake = FakeLLM([{"content": "hello"}])
    monkeypatch.setattr(agent.llm, "chat", fake)
    ev = run("next", [{"role": "system", "content": "old sys"}] + old)
    sent = fake.calls[0]["messages"]
    assert sum(m["role"] == "system" for m in sent) == 1 and sent[1]["content"] == "q0"
    hist = ev[-1].data["history"]
    assert len(hist) <= agent.HISTORY_KEEP and hist[0]["role"] == "user"
    assert hist[-1] == {"role": "assistant", "content": "hello"}


def test_resolve_date():
    mon = date(2026, 10, 26)   # a Monday
    r = lambda s: agent.resolve_date(s, mon)  # noqa: E731
    assert r("today") == "2026-10-26"
    assert r("tomorrow") == "2026-10-27"
    assert r("Friday") == "2026-10-30"
    assert r("fri") == "2026-10-30"
    assert r("monday") == "2026-10-26"
    assert r("next monday") == "2026-11-02"
    assert r("11/3") == "2026-11-03"
    assert r("1/5") == "2027-01-05"
    assert r("2026-12-01") == "2026-12-01"
    assert r(None) is None


def test_real_backends_wiring(monkeypatch):
    """track_flight / search_flights call providers + nl2sql with the right carrier/origin/hour."""
    import sys
    import types as t
    from flightwise.models import FlightOffer, FlightStatus, DelayRisk

    risk_calls = []

    def delay_risk(carrier, origin, hour=None, month=None):
        risk_calls.append((carrier, origin, hour))
        return DelayRisk(carrier=carrier, origin=origin, hour=hour, flights=100, pct_delayed_15=20.0,
                         avg_dep_delay=9.0, pct_cancelled=1.0, label="medium", sql="SELECT")

    async def get_flight_status(fn, date=None):
        return FlightStatus(flight_number=fn, airline_code="AA", origin="OKC", destination="DFW",
                            scheduled_departure="2026-10-26T07:30:00-05:00")

    async def search_flights(o, d, date, adults=1):
        return [FlightOffer(id=str(i), airline="X", airline_code="UA", flight_numbers=[f"UA{i}"], origin=o,
                            destination=d, departure=f"{date}T1{i}:00:00", arrival=f"{date}T1{i}:59:00",
                            duration_min=59, price=100 + i) for i in range(5)]

    nl = t.SimpleNamespace(delay_risk=delay_risk, ask=None)
    monkeypatch.setitem(sys.modules, "flightwise.data.nl2sql", nl)
    import flightwise.data as data_pkg
    monkeypatch.setattr(data_pkg, "nl2sql", nl, raising=False)
    import flightwise.providers as prov
    monkeypatch.setattr(prov, "status", t.SimpleNamespace(get_flight_status=get_flight_status), raising=False)
    monkeypatch.setattr(prov, "search", t.SimpleNamespace(search_flights=search_flights), raising=False)
    monkeypatch.setitem(sys.modules, "flightwise.providers.status", prov.status)
    monkeypatch.setitem(sys.modules, "flightwise.providers.search", prov.search)

    res, ok = asyncio.run(agent.call_tool("track_flight", {"flight_number": "AA100"}))
    assert ok and res["status"]["flight_number"] == "AA100" and res["risk"]["label"] == "medium"
    assert risk_calls[-1] == ("AA", "OKC", 7)

    res, ok = asyncio.run(agent.call_tool("search_flights", {"origin": "okc", "destination": "den", "date": "2026-10-30"}))
    assert ok and len(res) == 5
    assert all("risk" in o for o in res)
    text = agent.to_model_text(res)
    model_view = json.loads(text)
    assert len(model_view) == 5 and "sql" not in model_view[0]["risk"]
    assert json.loads(agent.to_model_text(res * 2))["total"] == 10   # long lists are capped + counted


def test_local_hour_for_bts():
    assert agent._hour_of("2026-10-26T22:44:00Z", "CLT") == 18      # EDT
    assert agent._hour_of("2026-10-26T22:44:00Z", "PHX") == 15      # no DST
    assert agent._hour_of("2026-10-26T22:44:00Z", "XYZ") is None    # unknown airport + UTC: don't guess
    assert agent._hour_of("2026-10-26T07:30:00", "XYZ") == 7        # naive = already local
    assert agent._local_str("2026-10-26T22:44:00Z", "CLT") == "Mon 18:44 local"


def test_recommendation_prefers_reliable_known_risk():
    offers = [
        {"price": 60, "stops": 0, "risk": {"label": "unknown", "pct_delayed_15": None}},
        {"price": 80, "stops": 0, "risk": {"label": "low", "pct_delayed_15": 12.0}},
        {"price": 70, "stops": 1, "risk": {"label": "medium", "pct_delayed_15": 26.0}},
        {"price": 50, "stops": 0, "risk": {"error": "delay history unavailable"}},
    ]
    agent._mark_recommended(offers)
    assert [bool(o.get("recommended")) for o in offers] == [True, False, False, False]
    assert "12%" in offers[0]["why"] and offers[0]["price"] == 80
