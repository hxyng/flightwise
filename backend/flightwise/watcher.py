"""Background flight watcher: polls watched flights, diffs, and fans events out to subscribers."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date as _date
from pathlib import Path

from . import config
from .models import FlightStatus, WatchedFlight, WatchEvent

log = logging.getLogger("flightwise.watcher")

DELAY_STEP_MIN = 5          # publish delay_change only when the delay moves by at least this
QUEUE_SIZE = 100
WATCHLIST_PATH = config.ROOT / "data" / "watchlist.json"


def _norm(flight_number: str) -> str:
    return "".join(flight_number.split()).upper()


async def _fetch_status(flight_number: str, date: str | None) -> FlightStatus:
    from .providers import status as status_provider   # lazy: built by B1
    return await status_provider.get_flight_status(flight_number, date)


def _fetch_risk(st: FlightStatus):
    """Delay risk from history; None on any failure."""
    try:
        from .data import nl2sql                          # lazy: built by B2
        from .agent import _hour_of                       # BTS hours are local, provider times UTC
        carrier = st.airline_code or "".join(c for c in st.flight_number if c.isalpha())[:2]
        hour = _hour_of(st.scheduled_departure, st.origin)
        return nl2sql.delay_risk(carrier, st.origin, hour)
    except Exception as e:  # noqa: BLE001
        log.info("delay_risk unavailable: %s", e)
        return None


def diff_status(old: FlightStatus | None, new: FlightStatus) -> list[tuple[str, str]]:
    """Return [(event_type, message)] describing what changed from old to new."""
    if old is None:
        return []
    fn = new.flight_number
    out: list[tuple[str, str]] = []
    od, nd = old.departure_delay_min or 0, new.departure_delay_min or 0
    delay_event = abs(nd - od) >= DELAY_STEP_MIN
    msg = ""
    if delay_event:
        if nd > 0:
            msg = f"{fn} is now delayed {nd} min (was {od})"
        else:
            msg = f"{fn} is back on time (was delayed {od} min)"
    if new.status != old.status and not (delay_event and new.status == "delayed"):
        phrases = {
            "departed": f"{fn} has departed",
            "en_route": f"{fn} is en route",
            "landed": f"{fn} has landed",
            "boarding": f"{fn} is now boarding",
            "cancelled": f"{fn} has been cancelled",
            "diverted": f"{fn} has been diverted",
            "delayed": f"{fn} is now delayed",
            "scheduled": f"{fn} is back on schedule",
        }
        out.append(("status_change", phrases.get(new.status, f"{fn} status is now {new.status}")))
    if delay_event:
        out.append(("delay_change", msg))
    if new.gate != old.gate and new.gate:
        if old.gate:
            out.append(("gate_change", f"{fn} gate changed {old.gate} → {new.gate}"))
        else:
            out.append(("gate_change", f"{fn} gate assigned: {new.gate}"))
    return out


class Watcher:
    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else WATCHLIST_PATH
        self._items: dict[str, WatchedFlight] = {}
        self._subs: list[asyncio.Queue] = []
        self._load()

    # persistence ---------------------------------------------------------
    def _load(self) -> None:
        try:
            for d in json.loads(self.path.read_text(encoding="utf-8")):
                w = WatchedFlight.model_validate(d)
                self._items[w.id] = w
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("could not load watchlist: %s", e)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = [w.model_dump(mode="json") for w in self._items.values()]
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as e:  # noqa: BLE001
            log.warning("could not save watchlist: %s", e)

    # pub/sub -------------------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subs:
            self._subs.remove(q)

    def publish(self, ev: WatchEvent) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass  # slow subscriber: drop rather than block

    # API -----------------------------------------------------------------
    def list(self) -> list[WatchedFlight]:
        return list(self._items.values())

    async def add(self, flight_number: str, date: str | None = None) -> WatchedFlight:
        fn = _norm(flight_number)
        day = date or _date.today().isoformat()
        wid = f"{fn}-{day}"
        if wid in self._items:
            return self._items[wid]
        st = await _fetch_status(fn, day)
        risk = await asyncio.to_thread(_fetch_risk, st)
        w = WatchedFlight(id=wid, flight_number=st.flight_number or fn, date=day,
                          last_status=st, risk=risk)
        self._items[wid] = w
        self._save()
        self.publish(WatchEvent(type="added", flight_id=wid, flight_number=w.flight_number,
                                message=f"Now watching {w.flight_number}", status=st))
        return w

    async def remove(self, flight_id: str) -> bool:
        w = self._items.pop(flight_id, None)
        if w is None:
            return False
        self._save()
        self.publish(WatchEvent(type="removed", flight_id=flight_id, flight_number=w.flight_number,
                                message=f"Stopped watching {w.flight_number}", status=w.last_status))
        return True

    async def poll_once(self) -> None:
        for w in list(self._items.values()):
            if w.id not in self._items:
                continue
            try:
                new = await _fetch_status(w.flight_number, w.date)
            except Exception as e:  # noqa: BLE001
                log.info("poll failed for %s: %s", w.id, e)
                continue
            for etype, msg in diff_status(w.last_status, new):
                self.publish(WatchEvent(type=etype, flight_id=w.id, flight_number=w.flight_number,
                                        message=msg, status=new))
            w.last_status = new
            self.publish(WatchEvent(type="tick", flight_id=w.id, flight_number=w.flight_number,
                                    message=f"{w.flight_number} {new.status}", status=new))
        self._save()

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("watcher cycle failed: %s", e)
            await asyncio.sleep(config.WATCH_INTERVAL_S)


watcher = Watcher()
