"""Flight status: AeroDataBox via API.market when keyed, else (or on any failure) mock."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .. import config
from ..models import FlightStatus
from . import mock

log = logging.getLogger(__name__)
TIMEOUT = 8.0


def use_real() -> bool:
    return bool(config.AERODATABOX_KEY) and not config.FORCE_MOCK


def _client() -> httpx.AsyncClient:
    # UNVERIFIED: the API.market auth header name.
    return httpx.AsyncClient(
        timeout=TIMEOUT,
        headers={"x-api-market-key": config.AERODATABOX_KEY, "accept": "application/json"},
    )


# --- parsing (defensive: every field optional) -----------------------------------------

def _dt(node: Any) -> datetime | None:
    """Accepts {"utc": "...", "local": "..."} or a bare string. Prefers UTC."""
    if isinstance(node, dict):
        node = node.get("utc") or node.get("local")
    if not isinstance(node, str) or not node:
        return None
    try:
        dt = datetime.fromisoformat(node.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _first(d: dict, *names: str) -> Any:
    for n in names:
        if d.get(n) is not None:
            return d[n]
    return None


_STATUS = {
    "expected": "scheduled", "checkin": "scheduled", "unknown": "scheduled",
    "boarding": "boarding", "gateclosed": "boarding", "departed": "departed",
    "enroute": "en_route", "approaching": "en_route", "arrived": "landed",
    "delayed": "delayed", "canceled": "cancelled", "cancelled": "cancelled",
    "canceleduncertain": "cancelled", "diverted": "diverted",
}


def parse_flight(item: dict, queried_airport: str | None = None, now: datetime | None = None) -> FlightStatus:
    """Normalize one AeroDataBox flight object. Raises on unusable data."""
    now = now or datetime.now(timezone.utc)
    dep = dict(item.get("departure") or {})
    arr = dict(item.get("arrival") or {})
    mv = item.get("movement") or {}
    if queried_airport and mv:
        # Airport board (departures): `movement` describes the far end of the flight.
        if not dep:
            dep = {"airport": {"iata": queried_airport}}
        if not arr.get("airport"):
            arr = {**mv, **arr}
    dep_ap = (dep.get("airport") or {}).get("iata") or queried_airport
    arr_ap = (arr.get("airport") or {}).get("iata")
    if not dep_ap or not arr_ap:
        raise ValueError("missing airports")
    num = mock.normalize_flight_number(item.get("number") or "")
    if not num:
        raise ValueError("missing flight number")
    airline = item.get("airline") or {}

    s_dep = _dt(_first(dep, "scheduledTime", "scheduledTimeUtc"))
    e_dep = _dt(_first(dep, "revisedTime", "predictedTime", "revisedTimeUtc"))
    a_dep = _dt(_first(dep, "runwayTime", "actualTime", "runwayTimeUtc"))
    s_arr = _dt(_first(arr, "scheduledTime", "scheduledTimeUtc"))
    e_arr = _dt(_first(arr, "revisedTime", "predictedTime", "revisedTimeUtc"))
    a_arr = _dt(_first(arr, "runwayTime", "actualTime", "runwayTimeUtc"))

    def delay(sched, est):
        return round((est - sched).total_seconds() / 60) if sched and est else None

    d_dep = delay(s_dep, a_dep or e_dep)
    d_arr = delay(s_arr, a_arr or e_arr)
    raw = str(item.get("status") or "unknown").replace(" ", "").lower()
    status = _STATUS.get(raw, "unknown")
    if status == "scheduled" and d_dep is not None and d_dep >= 15:
        status = "delayed"

    start, end = a_dep or e_dep or s_dep, a_arr or e_arr or s_arr
    if status == "landed":
        progress = 1.0
    elif status in ("departed", "en_route") and start and end and end > start:
        progress = max(0.0, min(1.0, (now - start) / (end - start)))
    else:
        progress = 0.0

    return FlightStatus(
        flight_number=num, airline=airline.get("name"), airline_code=airline.get("iata"),
        origin=dep_ap, destination=arr_ap,
        scheduled_departure=s_dep, estimated_departure=e_dep or a_dep, actual_departure=a_dep,
        scheduled_arrival=s_arr, estimated_arrival=e_arr or a_arr, actual_arrival=a_arr,
        status=status, departure_delay_min=d_dep, arrival_delay_min=d_arr,
        gate=dep.get("gate") or None, terminal=dep.get("terminal") or None,
        aircraft=(item.get("aircraft") or {}).get("model"),
        progress=round(progress, 3), source="aerodatabox",
    )


async def _fetch_status(fn: str, date: str) -> FlightStatus:
    async with _client() as c:
        r = await c.get(f"{config.AERODATABOX_URL.rstrip('/')}/flights/number/{fn}/{date}")
        r.raise_for_status()
        data = r.json()
    items = data if isinstance(data, list) else (data.get("flights") or [data])
    if not items:
        raise ValueError("no flights returned")
    items = sorted(items, key=lambda i: str(i.get("status")).lower().startswith("cancel"))
    return parse_flight(items[0])


async def get_flight_status(flight_number: str, date: str | None = None) -> FlightStatus:
    fn = mock.normalize_flight_number(flight_number)
    if not fn:
        raise ValueError("flight_number is required")
    day = date or datetime.now(timezone.utc).date().isoformat()
    if use_real():
        try:
            return await _fetch_status(fn, day)
        except Exception as e:  # HTTP error, timeout, parse failure
            log.warning("AeroDataBox status failed for %s (%s: %s); using mock", fn, type(e).__name__, e)
    return mock.mock_status(fn, day)


async def _fetch_departures(airport: str, limit: int) -> list[FlightStatus]:
    now = datetime.now(timezone.utc)
    frm = now.strftime("%Y-%m-%dT%H:%M")
    to = (now + timedelta(hours=11)).strftime("%Y-%m-%dT%H:%M")
    async with _client() as c:
        r = await c.get(
            f"{config.AERODATABOX_URL.rstrip('/')}/flights/airports/iata/{airport}/{frm}/{to}",
            params={"direction": "Departure", "withCancelled": "false", "withCodeshared": "false",
                    "withCargo": "false", "withPrivate": "false"},
        )
        r.raise_for_status()
        data = r.json()
    items = data.get("departures") if isinstance(data, dict) else data
    if not items:
        raise ValueError("no departures returned")
    out = []
    for it in items:
        try:
            out.append(parse_flight(it, queried_airport=airport))
        except Exception as e:
            log.debug("skipping unparsable departure: %s", e)
    if not out:
        raise ValueError("no parsable departures")
    out.sort(key=lambda s: s.scheduled_departure or datetime.max.replace(tzinfo=timezone.utc))
    return out[:limit]


async def get_departures(airport: str, limit: int = 20) -> list[FlightStatus]:
    ap = airport.strip().upper()
    if use_real():
        try:
            return await _fetch_departures(ap, limit)
        except Exception as e:
            log.warning("AeroDataBox departures failed for %s (%s: %s); using mock", ap, type(e).__name__, e)
    return mock.mock_departures(ap, limit)
