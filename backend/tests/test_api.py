import asyncio
import importlib
import json
import sys
import types

import pytest
from fastapi.testclient import TestClient

from flightwise import api, config, demo_cache, watcher as W
from flightwise.models import AgentEvent, DelayRisk, FlightOffer, FlightStatus, QueryResult
from datetime import datetime, timezone


def fake_module(monkeypatch, dotted, **attrs):
    """Install a fake submodule so lazy `from .pkg import name` finds it even if the real one exists."""
    mod = types.ModuleType(dotted)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, dotted, mod)
    parent, name = dotted.rsplit(".", 1)
    try:
        importlib.import_module(parent)
    except ImportError:            # sibling builder's package is half-built: stub the parent too
        stub = types.ModuleType(parent)
        stub.__path__ = []
        monkeypatch.setitem(sys.modules, parent, stub)
    monkeypatch.setattr(sys.modules[parent], name, mod, raising=False)
    return mod


def ST(**kw):
    base = dict(flight_number="AA100", airline_code="AA", origin="OKC", destination="DFW", status="boarding")
    base.update(kw)
    return FlightStatus(**base)


RISK = DelayRisk(carrier="AA", origin="OKC", hour=9, flights=5, pct_delayed_15=12.0, avg_dep_delay=4.0,
                 pct_cancelled=1.0, label="low", sql="select 1")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEMO_CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(W.watcher, "_items", {})
    monkeypatch.setattr(W.watcher, "_subs", [])
    monkeypatch.setattr(W.watcher, "path", tmp_path / "wl.json")

    async def get_status(fn, date=None):
        return ST(flight_number=fn.upper())

    async def search_flights(o, d, date, adults=1):
        now = datetime(2026, 10, 27, 9, tzinfo=timezone.utc)
        return [FlightOffer(id="1", airline="AA", flight_numbers=["AA1"], origin=o, destination=d,
                            departure=now, arrival=now, duration_min=90)]

    fake_module(monkeypatch, "flightwise.providers.status", get_flight_status=get_status,
                provider_names=lambda: {"status": "mock", "search": "mock"})
    fake_module(monkeypatch, "flightwise.providers.search", search_flights=search_flights)
    fake_module(monkeypatch, "flightwise.data.nl2sql", delay_risk=lambda c, o, h=None, m=None: RISK,
                ask=lambda q, explain=True: QueryResult(question=q, sql="select 1", columns=["a"],
                                                        rows=[[1]], answer="one", backend="duckdb"))
    fake_module(monkeypatch, "flightwise.data.db", backend_name=lambda: "duckdb")
    monkeypatch.setattr(api.llm, "health", lambda: True)
    return TestClient(api.app)


def sse_events(text):
    out, ev = [], None
    for line in text.splitlines():
        if line.startswith("event:"):
            ev = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and ev:
            out.append((ev, json.loads(line.split(":", 1)[1])))
            ev = None
    return out


def test_health(client):
    r = client.get("/api/health")
    assert r.json() == {"llm": True, "model": config.OLLAMA_MODEL, "db": "duckdb", "status": "mock", "search": "mock"}


def test_search_status_risk(client):
    r = client.get("/api/flights/search", params={"origin": "okc", "destination": "dfw", "date": "2026-10-27"})
    assert r.status_code == 200 and r.json()[0]["origin"] == "OKC"
    assert client.get("/api/flights/status/aa100").json()["flight_number"] == "AA100"
    assert client.get("/api/risk", params={"carrier": "aa", "origin": "okc", "hour": 9}).json()["label"] == "low"


def test_watch_crud(client):
    assert client.get("/api/watch").json() == []
    w = client.post("/api/watch", json={"flight_number": "aa100", "date": "2026-10-27"}).json()
    assert w["id"] == "AA100-2026-10-27" and w["risk"]["label"] == "low"
    assert len(client.get("/api/watch").json()) == 1
    assert client.delete(f"/api/watch/{w['id']}").json() == {"ok": True}
    assert client.delete(f"/api/watch/{w['id']}").status_code == 404


def test_friendly_errors(client, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("upstream down")
    monkeypatch.setattr(sys.modules["flightwise.providers.status"], "get_flight_status", boom)
    r = client.get("/api/flights/status/AA100")
    assert r.status_code == 502 and "upstream down" in r.json()["error"]
    r = client.post("/api/watch", json={"flight_number": "AA100"})
    assert r.status_code == 502 and "error" in r.json()


def test_ask_caches_and_falls_back(client, monkeypatch):
    q = "Which airline is most reliable?"
    r = client.post("/api/ask", json={"question": q})
    assert r.json()["answer"] == "one" and "x-flightwise-cache" not in r.headers
    nl = sys.modules["flightwise.data.nl2sql"]

    def down(*a, **k):
        raise ConnectionError("db down")
    monkeypatch.setattr(nl, "ask", down)
    r = client.post("/api/ask", json={"question": "which airline is MOST reliable"})
    assert r.headers["x-flightwise-cache"] == "demo" and "cached" in r.json()["answer"]
    r = client.post("/api/ask", json={"question": "something never asked"})
    assert r.status_code == 200 and r.json()["error"]


def agent(events):
    async def run_agent(message, history=None):
        for e in events:
            if isinstance(e, Exception):
                raise e
            yield e
    return run_agent


def test_chat_stream_and_cache(client, monkeypatch):
    evs = [AgentEvent(type="thinking", data={"text": "hm"}),
           AgentEvent(type="message", data={"text": "Fly at 7am."}),
           AgentEvent(type="done", data={"history": []})]
    fake_module(monkeypatch, "flightwise.agent", run_agent=agent(evs))
    r = client.post("/api/chat", json={"message": "Best time from OKC?"})
    assert [e for e, _ in sse_events(r.text)] == ["thinking", "message", "done"]
    # agent now fails -> cached final answer served
    fake_module(monkeypatch, "flightwise.agent", run_agent=agent([RuntimeError("ollama down")]))
    got = sse_events(client.post("/api/chat", json={"message": "best time from okc"}).text)
    assert [e for e, _ in got] == ["message", "done"] and "cached" in got[0][1]["data"]["text"]
    got = sse_events(client.post("/api/chat", json={"message": "unseen"}).text)
    assert [e for e, _ in got] == ["error", "done"]


def test_events_stream_generator(client):
    async def go():
        gen = api.event_stream()
        t = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.01)
        assert len(W.watcher._subs) == 1
        await W.watcher.add("AA100", "2026-10-27")
        ev = await asyncio.wait_for(t, 2)
        assert ev["event"] == "added" and json.loads(ev["data"])["flight_number"] == "AA100"
        await gen.aclose()
        assert W.watcher._subs == []
    asyncio.run(go())


def test_events_route_registered(client):
    assert any(getattr(r, "path", "") == "/api/events" for r in api.app.routes)


def test_demo_cache_normalize():
    assert demo_cache.normalize("  When's the BEST time?? ") == demo_cache.normalize("when s the best time")
