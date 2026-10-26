"""Deterministic, clock-driven mock flight data (offline fallback for the demo).

Status: each (flight_number, date) gets a schedule anchored near "now" the first time it is
seen in this process, then evolves with wall-clock time. About 1 in 3 flights pick up a delay
increase and/or gate change 30-100 s after first being seen, so a 20 s watcher sees events
within a 2-minute demo. Tests patch ``_now`` to control the clock.
"""
from __future__ import annotations

import hashlib
import math
import random
import re
from datetime import datetime, timedelta, timezone

from ..models import FlightOffer, FlightStatus

AIRLINES = {
    "AA": "American Airlines", "DL": "Delta Air Lines", "UA": "United Airlines",
    "WN": "Southwest Airlines", "AS": "Alaska Airlines", "B6": "JetBlue Airways",
    "NK": "Spirit Airlines", "F9": "Frontier Airlines",
}
# iata: (lat, lon)
AIRPORTS = {
    "OKC": (35.393, -97.601), "DFW": (32.897, -97.038), "DEN": (39.856, -104.674),
    "ORD": (41.978, -87.905), "ATL": (33.637, -84.428), "LAX": (33.942, -118.408),
    "JFK": (40.640, -73.779), "SFO": (37.619, -122.375), "IAH": (29.984, -95.341),
    "PHX": (33.434, -112.012), "SEA": (47.450, -122.309), "MIA": (25.793, -80.291),
    "BOS": (42.364, -71.005), "LAS": (36.084, -115.154), "MSP": (44.882, -93.222),
    "CLT": (35.214, -80.943),
}
HUBS = {"AA": ["DFW", "CLT", "ORD", "MIA"], "DL": ["ATL", "MSP", "SEA", "JFK"],
        "UA": ["ORD", "DEN", "IAH", "SFO"], "WN": ["DEN", "PHX", "LAS", "OKC"],
        "AS": ["SEA", "SFO", "LAX"], "B6": ["JFK", "BOS", "MIA"],
        "NK": ["MIA", "LAS", "ORD"], "F9": ["DEN", "LAS", "PHX"]}
AIRCRAFT = ["Boeing 737-800", "Airbus A320", "Airbus A321", "Boeing 737 MAX 8",
            "Boeing 787-9", "Embraer 175", "Airbus A319"]

_anchors: dict[tuple[str, str], datetime] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def reset() -> None:
    _anchors.clear()


def normalize_flight_number(fn: str) -> str:
    return re.sub(r"[\s\-]+", "", (fn or "")).upper()


def split_flight_number(fn: str) -> tuple[str, str]:
    m = re.match(r"^([A-Z0-9]{2})(\d{1,4}[A-Z]?)$", fn)
    return (m.group(1), m.group(2)) if m else (fn[:2], fn[2:])


def _rng(*parts: object) -> random.Random:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def distance_mi(a: str, b: str) -> float:
    (la1, lo1), (la2, lo2) = (tuple(map(math.radians, AIRPORTS[c])) for c in (a, b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def block_minutes(a: str, b: str) -> int:
    return int(35 + distance_mi(a, b) / 8.0)   # ~480 mph plus taxi/climb


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def mock_status(flight_number: str, date: str | None = None, origin: str | None = None,
                destination: str | None = None) -> FlightStatus:
    fn = normalize_flight_number(flight_number)
    now = _now()
    date = date or now.date().isoformat()
    code, _num = split_flight_number(fn)
    r = _rng("status", fn, date)

    hubs = HUBS.get(code, list(AIRPORTS))
    o = origin or r.choice(hubs)
    d = destination or r.choice([a for a in AIRPORTS if a != o])
    if d == o:
        d = r.choice([a for a in AIRPORTS if a != o])
    block = block_minutes(o, d)

    first_seen = _anchors.setdefault((fn, date), now)
    # Anchor: 70% depart 5-40 min after first sight, 30% already in progress.
    if r.random() < 0.7:
        offset = r.randint(5, 40)
    else:
        offset = -r.randint(10, max(11, min(50, block - 20)))
    sched_dep = (first_seen + timedelta(minutes=offset)).replace(second=0, microsecond=0)
    sched_arr = sched_dep + timedelta(minutes=block)

    # Delay / gate evolution.
    delay = r.choice([0, 0, 0, 0, 0, 5, 10])
    gate = f"{r.choice('ABCDE')}{r.randint(1, 38)}"
    terminal = r.choice(["A", "B", "C", "D", "1", "2", "3"])
    changer = r.random() < 0.34
    change_after = timedelta(seconds=r.randint(30, 100))
    if changer:
        kind = r.choice(["delay", "gate", "both"])
        delay_bump = r.randint(1, 3) * 15 if kind in ("delay", "both") else 0
        new_gate = None
        if kind in ("gate", "both"):
            new_gate = f"{r.choice('ABCDE')}{r.randint(1, 38)}"
            if new_gate == gate:
                new_gate = f"{gate[0]}{int(gate[1:]) % 38 + 1}"
        if now - first_seen >= change_after:
            delay += delay_bump
            gate = new_gate or gate

    est_dep = sched_dep + timedelta(minutes=delay)
    est_arr = sched_arr + timedelta(minutes=delay)
    status, actual_dep, actual_arr, progress = "scheduled", None, None, 0.0
    if now >= est_arr:
        status, actual_dep, actual_arr, progress = "landed", est_dep, est_arr, 1.0
    elif now >= est_dep:
        actual_dep = est_dep
        progress = _clamp01((now - est_dep) / (est_arr - est_dep))
        status = "departed" if now - est_dep < timedelta(minutes=10) else "en_route"
    elif est_dep - now <= timedelta(minutes=30):
        status = "boarding"
    elif delay >= 15:
        status = "delayed"

    return FlightStatus(
        flight_number=fn, airline=AIRLINES.get(code), airline_code=code, origin=o, destination=d,
        scheduled_departure=sched_dep, estimated_departure=est_dep, actual_departure=actual_dep,
        scheduled_arrival=sched_arr, estimated_arrival=est_arr, actual_arrival=actual_arr,
        status=status, departure_delay_min=delay, arrival_delay_min=delay,
        gate=gate, terminal=terminal, aircraft=r.choice(AIRCRAFT),
        progress=round(progress, 3), source="mock", updated_at=now,
    )


def mock_departures(airport: str, limit: int = 20) -> list[FlightStatus]:
    airport = airport.upper()
    if airport not in AIRPORTS:
        airport = "OKC"
    date = _now().date().isoformat()
    r = _rng("departures", airport)
    out = []
    for _ in range(max(0, limit)):
        code = r.choice(list(AIRLINES))
        fn = f"{code}{r.randint(100, 2999)}"
        dest = r.choice([a for a in AIRPORTS if a != airport])
        out.append(mock_status(fn, date, origin=airport, destination=dest))
    out.sort(key=lambda s: s.scheduled_departure)
    return out


def mock_offers(origin: str, destination: str, date: str, adults: int = 1) -> list[FlightOffer]:
    o, d = origin.upper(), destination.upper()
    r = _rng("search", o, d, date)
    try:
        day = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    except ValueError:
        day = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    if o in AIRPORTS and d in AIRPORTS and o != d:
        base_block, miles = block_minutes(o, d), distance_mi(o, d)
    else:
        base_block, miles = r.randint(90, 300), r.randint(400, 1800)
    offers = []
    for i in range(r.randint(5, 8)):
        code = r.choice(list(AIRLINES))
        stops = 1 if r.random() < 0.35 else 0
        dur = base_block + (r.randint(50, 130) if stops else r.randint(0, 20))
        dep = day + timedelta(hours=r.randint(5, 21), minutes=r.choice([0, 5, 15, 20, 30, 45, 50]))
        price = (60 + miles * 0.11) * (0.8 if stops else 1.0) * r.uniform(0.8, 1.5)
        if code in ("NK", "F9"):
            price *= 0.75
        fns = [f"{code}{r.randint(100, 2999)}"]
        if stops:
            fns.append(f"{code}{r.randint(100, 2999)}")
        offers.append(FlightOffer(
            id=hashlib.md5(f"{o}{d}{date}{i}{fns}".encode()).hexdigest()[:10],
            airline=AIRLINES[code], airline_code=code, flight_numbers=fns, origin=o,
            destination=d, departure=dep, arrival=dep + timedelta(minutes=dur),
            duration_min=dur, stops=stops, price=float(round(price * max(adults, 1))), source="mock",
        ))
    offers.sort(key=lambda x: (x.price or 0))
    return offers
