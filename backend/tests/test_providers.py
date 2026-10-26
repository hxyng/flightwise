import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from flightwise import config
from flightwise.models import FlightOffer, FlightStatus
from flightwise.providers import mock, provider_names, search, status

T0 = datetime(2026, 10, 26, 18, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    mock.reset()
    monkeypatch.setattr(config, "FORCE_MOCK", False)
    monkeypatch.setattr(config, "AERODATABOX_KEY", "")
    monkeypatch.setattr(config, "SERPAPI_KEY", "")
    yield
    mock.reset()


def clock(monkeypatch, t):
    monkeypatch.setattr(mock, "_now", lambda: t)


def run(coro):
    return asyncio.run(coro)


def test_normalize_and_mock_status(monkeypatch):
    clock(monkeypatch, T0)
    s = run(status.get_flight_status("aa 100", "2026-10-26"))
    assert isinstance(s, FlightStatus)
    assert s.flight_number == "AA100" and s.airline_code == "AA" and s.source == "mock"
    assert s.origin != s.destination
    assert 0 <= s.progress <= 1
    assert s.scheduled_departure and s.scheduled_departure.tzinfo


def test_deterministic_route():
    a = mock.mock_status("DL 2201", "2026-10-26")
    mock.reset()
    b = mock.mock_status("dl2201", "2026-10-26")
    assert (a.origin, a.destination, a.aircraft) == (b.origin, b.destination, b.aircraft)


def test_status_evolves_with_clock(monkeypatch):
    clock(monkeypatch, T0)
    seen_change = 0
    for n in range(100, 160):
        fn = f"AA{n}"
        mock.mock_status(fn, "d")
    for n in range(100, 160):
        fn = f"AA{n}"
        clock(monkeypatch, T0)
        before = mock.mock_status(fn, "d")
        clock(monkeypatch, T0 + timedelta(seconds=110))
        after = mock.mock_status(fn, "d")
        if (before.gate, before.departure_delay_min) != (after.gate, after.departure_delay_min):
            seen_change += 1
    assert 8 <= seen_change <= 35  # roughly 1 in 3 of 60


def test_phases_progress(monkeypatch):
    clock(monkeypatch, T0)
    s0 = mock.mock_status("UA500", "d")
    seq = [s0.status]
    for minutes in (35, 60, 120, 400):
        clock(monkeypatch, T0 + timedelta(minutes=minutes))
        seq.append(mock.mock_status("UA500", "d").status)
    assert seq[-1] == "landed"
    assert any(x in seq for x in ("en_route", "departed"))
    last = mock.mock_status("UA500", "d")
    assert last.progress == 1.0 and last.actual_arrival


def test_departures_and_search_mock():
    deps = run(status.get_departures("okc", 5))
    assert len(deps) == 5 and all(d.origin == "OKC" for d in deps)
    offers = run(search.search_flights("OKC", "DEN", "2026-11-15"))
    assert 5 <= len(offers) <= 8
    for o in offers:
        assert isinstance(o, FlightOffer) and o.stops in (0, 1) and o.price > 0
        assert o.duration_min > 0 and o.arrival > o.departure
        assert len(o.flight_numbers) == o.stops + 1
    assert run(search.search_flights("XXX", "YYY", "2026-11-15"))


def test_provider_names(monkeypatch):
    assert provider_names() == {"status": "mock", "search": "mock"}
    monkeypatch.setattr(config, "AERODATABOX_KEY", "k")
    monkeypatch.setattr(config, "SERPAPI_KEY", "k")
    assert provider_names() == {"status": "aerodatabox", "search": "serpapi"}
    monkeypatch.setattr(config, "FORCE_MOCK", True)
    assert provider_names() == {"status": "mock", "search": "mock"}


ADB = [{
    "number": "AA 100", "status": "EnRoute", "airline": {"name": "American Airlines", "iata": "AA"},
    "departure": {"airport": {"iata": "JFK"}, "gate": "B22", "terminal": "8",
                  "scheduledTime": {"utc": "2026-10-26 17:00Z"}, "revisedTime": {"utc": "2026-10-26 17:25Z"}},
    "arrival": {"airport": {"iata": "LAX"}, "scheduledTime": {"utc": "2026-10-26 23:00Z"},
                "revisedTime": {"utc": "2026-10-26 23:30Z"}},
    "aircraft": {"model": "Boeing 777"},
}]


REAL_CLIENT = httpx.AsyncClient


def patch_client(monkeypatch, module, handler):
    transport = httpx.MockTransport(handler)
    if module is status:
        monkeypatch.setattr(status, "_client", lambda: REAL_CLIENT(transport=transport))
    else:
        monkeypatch.setattr(search.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=transport))


def test_aerodatabox_parse(monkeypatch):
    monkeypatch.setattr(config, "AERODATABOX_KEY", "k")
    patch_client(monkeypatch, status, lambda req: httpx.Response(200, json=ADB))
    s = run(status.get_flight_status("aa 100", "2026-10-26"))
    assert s.source == "aerodatabox" and s.flight_number == "AA100"
    assert (s.origin, s.destination, s.gate, s.status) == ("JFK", "LAX", "B22", "en_route")
    assert s.departure_delay_min == 25 and s.arrival_delay_min == 30


def test_status_fallback_on_http_error_and_garbage(monkeypatch):
    monkeypatch.setattr(config, "AERODATABOX_KEY", "k")
    patch_client(monkeypatch, status, lambda req: httpx.Response(500))
    assert run(status.get_flight_status("AA100")).source == "mock"
    patch_client(monkeypatch, status, lambda req: httpx.Response(200, json=[{"weird": 1}]))
    assert run(status.get_flight_status("AA100")).source == "mock"

    def boom(req):
        raise httpx.ConnectTimeout("slow")

    patch_client(monkeypatch, status, boom)
    assert run(status.get_flight_status("AA100")).source == "mock"
    assert all(d.source == "mock" for d in run(status.get_departures("DFW", 3)))


def test_force_mock_ignores_key(monkeypatch):
    monkeypatch.setattr(config, "AERODATABOX_KEY", "k")
    monkeypatch.setattr(config, "FORCE_MOCK", True)

    def boom(req):
        raise AssertionError("network used")

    patch_client(monkeypatch, status, boom)
    assert run(status.get_flight_status("AA100")).source == "mock"


def test_airport_board_parse(monkeypatch):
    monkeypatch.setattr(config, "AERODATABOX_KEY", "k")
    body = {"departures": [{
        "number": "WN 12", "status": "Expected", "airline": {"name": "Southwest", "iata": "WN"},
        "movement": {"airport": {"iata": "DEN"}, "scheduledTime": {"utc": "2026-10-26 20:00Z"}},
        "departure": {"scheduledTime": {"utc": "2026-10-26 19:00Z"}, "gate": "A1"},
    }]}
    patch_client(monkeypatch, status, lambda req: httpx.Response(200, json=body))
    out = run(status.get_departures("OKC", 5))
    assert out[0].source == "aerodatabox" and out[0].origin == "OKC" and out[0].destination == "DEN"


SERP = {"best_flights": [{
    "flights": [{"departure_airport": {"id": "OKC", "time": "2026-11-15 08:00"},
                 "arrival_airport": {"id": "DFW", "time": "2026-11-15 09:00"},
                 "airline": "American", "flight_number": "AA 321"},
                {"departure_airport": {"id": "DFW", "time": "2026-11-15 10:00"},
                 "arrival_airport": {"id": "DEN", "time": "2026-11-15 11:30"},
                 "airline": "American", "flight_number": "AA 77"}],
    "layovers": [{"duration": 60, "id": "DFW"}], "total_duration": 210, "price": 199}],
    "other_flights": [{"garbage": True}]}


def test_serpapi_parse_and_fallback(monkeypatch):
    monkeypatch.setattr(config, "SERPAPI_KEY", "k")
    patch_client(monkeypatch, search, lambda req: httpx.Response(200, json=SERP))
    offers = run(search.search_flights("okc", "den", "2026-11-15"))
    assert len(offers) == 1 and offers[0].source == "serpapi"
    o = offers[0]
    assert o.flight_numbers == ["AA321", "AA77"] and o.stops == 1 and o.price == 199
    assert o.duration_min == 210 and o.airline_code == "AA"

    patch_client(monkeypatch, search, lambda req: httpx.Response(429))
    assert all(x.source == "mock" for x in run(search.search_flights("OKC", "DEN", "2026-11-15")))
    patch_client(monkeypatch, search, lambda req: httpx.Response(200, json={"error": "bad key"}))
    assert all(x.source == "mock" for x in run(search.search_flights("OKC", "DEN", "2026-11-15")))
