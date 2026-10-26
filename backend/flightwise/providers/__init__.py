"""Flight data providers (real APIs with deterministic mock fallbacks)."""
from __future__ import annotations

from .. import config
from .search import search_flights
from .status import get_departures, get_flight_status


def provider_names() -> dict:
    return {
        "status": "aerodatabox" if config.AERODATABOX_KEY and not config.FORCE_MOCK else "mock",
        "search": "serpapi" if config.SERPAPI_KEY and not config.FORCE_MOCK else "mock",
    }


__all__ = ["get_flight_status", "get_departures", "search_flights", "provider_names"]
