import asyncio

from flightwise import watcher as W
from flightwise.models import DelayRisk, FlightStatus


def st(**kw):
    base = dict(flight_number="DL204", airline_code="DL", origin="OKC", destination="ATL",
                status="scheduled", departure_delay_min=0, gate="B12")
    base.update(kw)
    return FlightStatus(**base)


def types_msgs(old, new):
    return W.diff_status(old, new)


def test_diff_messages():
    assert W.diff_status(None, st()) == []
    assert W.diff_status(st(), st()) == []
    d = W.diff_status(st(status="delayed", departure_delay_min=10),
                      st(status="delayed", departure_delay_min=25))
    assert d == [("delay_change", "DL204 is now delayed 25 min (was 10)")]
    # below threshold: no event
    assert W.diff_status(st(departure_delay_min=10), st(departure_delay_min=14)) == []
    d = W.diff_status(st(flight_number="AA100"), st(flight_number="AA100", gate="C3"))
    assert d == [("gate_change", "AA100 gate changed B12 → C3")]
    d = W.diff_status(st(flight_number="UA88"), st(flight_number="UA88", status="departed"))
    assert d == [("status_change", "UA88 has departed")]
    d = W.diff_status(st(departure_delay_min=30, status="delayed"), st(departure_delay_min=0, status="scheduled"))
    assert [t for t, _ in d] == ["status_change", "delay_change"]
    assert "back on time" in d[1][1]


def make(tmp_path, monkeypatch, statuses):
    """Watcher whose provider returns successive statuses from `statuses` (last one repeats)."""
    seq = list(statuses)

    async def fake_fetch(fn, date):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    monkeypatch.setattr(W, "_fetch_status", fake_fetch)
    monkeypatch.setattr(W, "_fetch_risk", lambda s: DelayRisk(
        carrier="DL", origin="OKC", flights=10, pct_delayed_15=20, avg_dep_delay=5,
        pct_cancelled=1, label="low", sql="select 1"))
    return W.Watcher(path=tmp_path / "wl.json")


def drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_add_poll_fanout_and_persistence(tmp_path, monkeypatch):
    async def go():
        w = make(tmp_path, monkeypatch, [st(), st(), st(status="delayed", departure_delay_min=25, gate="C3")])
        q1, q2 = w.subscribe(), w.subscribe()
        item = await w.add("dl 204", "2026-10-27")
        assert item.id == "DL204-2026-10-27" and item.risk.label == "low"
        assert (await w.add("DL204", "2026-10-27")) is item          # idempotent
        await w.poll_once()                                           # no change -> tick only
        await w.poll_once()                                           # delay + gate change
        for q in (q1, q2):
            evs = drain(q)
            kinds = [e.type for e in evs]
            assert kinds[0] == "added"
            assert kinds.count("tick") == 2
            assert "delay_change" in kinds and "gate_change" in kinds
            assert any(e.message == "DL204 is now delayed 25 min (was 0)" for e in evs)
        w.unsubscribe(q2)
        await w.poll_once()
        assert drain(q2) == [] and drain(q1)
        # persistence across restart
        w2 = W.Watcher(path=tmp_path / "wl.json")
        assert [x.id for x in w2.list()] == ["DL204-2026-10-27"]
        assert w2.list()[0].last_status.gate == "C3"
        assert await w.remove(item.id) is True and await w.remove(item.id) is False
        assert W.Watcher(path=tmp_path / "wl.json").list() == []
    asyncio.run(go())


def test_slow_subscriber_dropped_not_blocking(tmp_path, monkeypatch):
    async def go():
        w = make(tmp_path, monkeypatch, [st()])
        q = w.subscribe()
        await w.add("DL204", "2026-10-27")
        for _ in range(W.QUEUE_SIZE + 20):
            await w.poll_once()          # must not block or raise
        assert q.full()
    asyncio.run(go())


def test_risk_failure_tolerated(tmp_path, monkeypatch):
    # real _fetch_risk with nl2sql missing/raising must give None
    from flightwise.data import nl2sql

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(nl2sql, "delay_risk", boom)
    assert W._fetch_risk(st()) is None


def test_run_loop_polls(tmp_path, monkeypatch):
    async def go():
        w = make(tmp_path, monkeypatch, [st()])
        monkeypatch.setattr(W.config, "WATCH_INTERVAL_S", 0.01)
        q = w.subscribe()
        await w.add("DL204", "2026-10-27")
        t = asyncio.create_task(w.run())
        await asyncio.sleep(0.1)
        t.cancel()
        assert sum(e.type == "tick" for e in drain(q)) >= 2
    asyncio.run(go())
