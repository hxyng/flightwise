"""Settings from environment / .env. Missing keys mean the matching mock is used."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


OLLAMA_URL = _get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = _get("OLLAMA_MODEL", "gemma4:12b")

AERODATABOX_KEY = _get("AERODATABOX_KEY")        # API.market key; empty -> mock status
AERODATABOX_URL = _get("AERODATABOX_URL", "https://prod.api.market/api/v1/aedbx/aerodatabox")
SERPAPI_KEY = _get("SERPAPI_KEY")                # empty -> mock search
FORCE_MOCK = _get("FLIGHTWISE_MOCK") == "1"      # demo safety switch: ignore all keys

SNOWFLAKE = {
    "account": _get("SNOWFLAKE_ACCOUNT"),
    "user": _get("SNOWFLAKE_USER"),
    "password": _get("SNOWFLAKE_PASSWORD"),      # password or PAT
    "warehouse": _get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
    "database": _get("SNOWFLAKE_DATABASE", "FLIGHTWISE"),
    "schema": _get("SNOWFLAKE_SCHEMA", "PUBLIC"),
    "role": _get("SNOWFLAKE_ROLE"),
}
USE_SNOWFLAKE = bool(SNOWFLAKE["account"] and SNOWFLAKE["user"]) and _get("FLIGHTWISE_DB") != "duckdb"
FLIGHTS_TABLE = _get("FLIGHTS_TABLE", "FLIGHTS")
DUCKDB_PARQUET = ROOT / "data" / "flights.parquet"   # offline fallback, built by scripts/fetch_bts.py

WATCH_INTERVAL_S = int(_get("WATCH_INTERVAL_S", "20"))
DEMO_CACHE = ROOT / "data" / "demo_cache.json"
