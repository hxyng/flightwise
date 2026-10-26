"""Query backend: Snowflake when configured, else DuckDB over data/flights.parquet.

One lazy connection per process; Snowflake connect failure falls back to DuckDB.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import pandas as pd

from .. import config

log = logging.getLogger(__name__)
_lock = threading.RLock()
_conn: Any = None
_backend: str | None = None
_schema_cache: str | None = None

COLUMNS: list[tuple[str, str, str]] = [
    ("FL_DATE", "DATE", "scheduled departure date (2026-06-01 .. 2026-08-31)"),
    ("MONTH", "INT", "month number 1-12"),
    ("DAY_OF_WEEK", "INT", "1=Monday .. 7=Sunday"),
    ("CARRIER", "TEXT", "airline code, e.g. AA, DL, UA, WN"),
    ("CARRIER_NAME", "TEXT", "airline name, e.g. 'Delta Air Lines'"),
    ("FLIGHT_NUM", "INT", "flight number without carrier code"),
    ("ORIGIN", "TEXT", "origin airport IATA code, e.g. OKC, DFW"),
    ("ORIGIN_CITY", "TEXT", "origin city, e.g. 'Oklahoma City, OK'"),
    ("DEST", "TEXT", "destination airport IATA code"),
    ("DEST_CITY", "TEXT", "destination city"),
    ("CRS_DEP_TIME", "INT", "scheduled departure local time as hhmm (905 = 09:05)"),
    ("DEP_HOUR", "INT", "scheduled departure hour 0-23 (local)"),
    ("DEP_DELAY", "FLOAT", "departure delay minutes (negative = early); NULL if cancelled"),
    ("DEP_DEL15", "INT", "1 if departure delayed >= 15 min else 0; NULL if cancelled"),
    ("ARR_DELAY", "FLOAT", "arrival delay minutes; NULL if cancelled"),
    ("ARR_DEL15", "INT", "1 if arrival delayed >= 15 min else 0; NULL if cancelled"),
    ("CANCELLED", "INT", "1 if the flight was cancelled else 0"),
    ("CANCELLATION_CODE", "TEXT", "A=carrier B=weather C=air traffic system D=security; NULL if not cancelled"),
    ("DISTANCE", "FLOAT", "route distance in miles"),
    ("CARRIER_DELAY", "FLOAT", "minutes of delay caused by the airline (only when ARR_DEL15=1)"),
    ("WEATHER_DELAY", "FLOAT", "minutes of delay caused by weather (only when ARR_DEL15=1)"),
    ("NAS_DELAY", "FLOAT", "minutes of delay caused by air traffic system (only when ARR_DEL15=1)"),
    ("LATE_AIRCRAFT_DELAY", "FLOAT", "minutes of delay caused by a late inbound aircraft (only when ARR_DEL15=1)"),
]


def _connect_snowflake():
    import snowflake.connector

    s = {k: v for k, v in config.SNOWFLAKE.items() if v}
    return snowflake.connector.connect(login_timeout=20, network_timeout=60, **s)


def _connect_duckdb():
    import duckdb

    if not config.DUCKDB_PARQUET.exists():
        raise FileNotFoundError(f"{config.DUCKDB_PARQUET} missing; run backend/scripts/fetch_bts.py")
    con = duckdb.connect(":memory:")
    p = config.DUCKDB_PARQUET.as_posix().replace("'", "''")
    con.execute(f"CREATE VIEW FLIGHTS AS SELECT * FROM read_parquet('{p}')")
    return con


def _get_conn():
    global _conn, _backend
    with _lock:
        if _conn is None:
            if config.USE_SNOWFLAKE:
                try:
                    _conn, _backend = _connect_snowflake(), "snowflake"
                except Exception as e:  # noqa: BLE001 - any connect failure falls back
                    log.warning("Snowflake connect failed (%s); falling back to DuckDB", e)
            if _conn is None:
                _conn, _backend = _connect_duckdb(), "duckdb"
        return _conn


def backend_name() -> str:
    _get_conn()
    return _backend or "duckdb"


def run_query(sql: str) -> pd.DataFrame:
    """Run SQL on the active backend. Column names are returned UPPERCASE on both."""
    con = _get_conn()
    with _lock:
        if _backend == "snowflake":
            cur = con.cursor()
            try:
                cur.execute(sql)
                df = cur.fetch_pandas_all()
            finally:
                cur.close()
        else:
            df = con.execute(sql).fetchdf()
    df.columns = [str(c).upper() for c in df.columns]
    return df


def get_schema() -> str:
    """Compact description of FLIGHTS (type, meaning, example values). Cached."""
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache
    lines = [f"Table FLIGHTS ({backend_name()}), one row per scheduled US domestic flight:"]
    lines += [f"- {n} {t}: {d}" for n, t, d in COLUMNS]
    try:
        cars = run_query("SELECT CARRIER, CARRIER_NAME, COUNT(*) AS N FROM FLIGHTS GROUP BY CARRIER, CARRIER_NAME "
                         "ORDER BY N DESC LIMIT 10")
        orgs = run_query("SELECT ORIGIN, COUNT(*) AS N FROM FLIGHTS GROUP BY ORIGIN ORDER BY N DESC LIMIT 15")
        tot = run_query("SELECT COUNT(*) AS N, MIN(FL_DATE) AS D0, MAX(FL_DATE) AS D1 FROM FLIGHTS").iloc[0]
        lines.append("Top carriers: " + ", ".join(f"{r.CARRIER}={r.CARRIER_NAME}" for r in cars.itertuples()))
        lines.append("Busiest origins: " + ", ".join(orgs["ORIGIN"]))
        lines.append(f"Rows: {int(tot['N'])}, dates {tot['D0']} to {tot['D1']}.")
    except Exception as e:  # noqa: BLE001 - schema is still useful without examples
        log.warning("schema sampling failed: %s", e)
        lines.append("Top carriers: AA, DL, UA, WN, OO, AS, B6. Airports use 3-letter IATA codes.")
    _schema_cache = "\n".join(lines)
    return _schema_cache
