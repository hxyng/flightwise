"""Flight search: SerpApi google_flights when keyed, else (or on any failure) mock."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from .. import config
from ..models import FlightOffer
from . import mock

log = logging.getLogger(__name__)
TIMEOUT = 8.0
SERPAPI_URL = "https://serpapi.com/search"


def use_real() -> bool:
    return bool(config.SERPAPI_KEY) and not config.FORCE_MOCK


def _t(s: Any) -> datetime:
    dt = datetime.fromisoformat(str(s).replace(" ", "T"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_offers(data: dict, origin: str, destination: str, currency: str = "USD") -> list[FlightOffer]:
    if data.get("error"):
        raise ValueError(f"serpapi error: {data['error']}")
    groups = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    out: list[FlightOffer] = []
    for g in groups:
        try:
            segs = g["flights"]
            first, last = segs[0], segs[-1]
            dep, arr = _t(first["departure_airport"]["time"]), _t(last["arrival_airport"]["time"])
            nums = [mock.normalize_flight_number(s.get("flight_number", "")) for s in segs]
            nums = [n for n in nums if n]
            dur = g.get("total_duration") or int((arr - dep).total_seconds() // 60)
            price = g.get("price")
            code = mock.split_flight_number(nums[0])[0] if nums else None
            out.append(FlightOffer(
                id=hashlib.md5(f"{nums}{dep}{price}".encode()).hexdigest()[:10],
                airline=first.get("airline") or code or "Unknown", airline_code=code,
                flight_numbers=nums,
                origin=first["departure_airport"].get("id") or origin,
                destination=last["arrival_airport"].get("id") or destination,
                departure=dep, arrival=arr, duration_min=int(dur),
                stops=len(g.get("layovers") or []) or max(len(segs) - 1, 0),
                price=float(price) if price is not None else None,
                currency=currency, source="serpapi",
            ))
        except (KeyError, IndexError, ValueError, TypeError) as e:
            log.debug("skipping unparsable offer: %s", e)
    if not out:
        raise ValueError("no parsable offers")
    return out[:10]


async def _fetch(origin: str, destination: str, date: str, adults: int) -> list[FlightOffer]:
    params = {"engine": "google_flights", "departure_id": origin, "arrival_id": destination,
              "outbound_date": date, "type": 2, "adults": adults, "currency": "USD", "hl": "en",
              "api_key": config.SERPAPI_KEY}
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(SERPAPI_URL, params=params)
        r.raise_for_status()
        return parse_offers(r.json(), origin, destination)


async def search_flights(origin: str, destination: str, date: str, adults: int = 1) -> list[FlightOffer]:
    o, d = origin.strip().upper(), destination.strip().upper()
    if use_real():
        try:
            return await _fetch(o, d, date, adults)
        except Exception as e:
            log.warning("SerpApi search failed for %s-%s (%s: %s); using mock", o, d, type(e).__name__, e)
    return mock.mock_offers(o, d, date, adults)
