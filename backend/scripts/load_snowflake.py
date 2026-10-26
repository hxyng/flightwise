"""Load data/flights.csv.gz into Snowflake FLIGHTWISE.PUBLIC.FLIGHTS (idempotent).

Usage (from backend/):  python scripts/load_snowflake.py
Reads SNOWFLAKE_* from ROOT/.env via flightwise.config. UNTESTED: written without a Snowflake account.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import snowflake.connector  # noqa: E402

from flightwise import config  # noqa: E402

FILE = ROOT / "data" / "flights.csv.gz"
SQL_FILE = Path(__file__).with_name("setup_snowflake.sql")


def statements(text: str) -> list[str]:
    text = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
    return [s.strip() for s in text.split(";") if s.strip()]


def main() -> int:
    s = config.SNOWFLAKE
    if not (s["account"] and s["user"] and s["password"]):
        print("Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD in .env first.")
        return 1
    if not FILE.exists():
        print(f"{FILE} missing; run scripts/fetch_bts.py first.")
        return 1
    params = {k: v for k, v in s.items() if v and k not in ("database", "schema")}
    con = snowflake.connector.connect(**params)
    cur = con.cursor()
    try:
        for stmt in statements(SQL_FILE.read_text(encoding="utf-8")):
            print("->", re.sub(r"\s+", " ", stmt)[:90])
            cur.execute(stmt)
        print("uploading", FILE.name, f"({FILE.stat().st_size // 1_000_000} MB) ...")
        cur.execute(f"PUT 'file://{FILE.as_posix()}' @FLIGHTS_STAGE OVERWRITE = TRUE AUTO_COMPRESS = FALSE")
        cur.execute("TRUNCATE TABLE FLIGHTS")
        cur.execute("COPY INTO FLIGHTS FROM @FLIGHTS_STAGE/flights.csv.gz "
                    "FILE_FORMAT = (FORMAT_NAME = FLIGHTS_CSV) ON_ERROR = ABORT_STATEMENT")
        cur.execute("SELECT COUNT(*) FROM FLIGHTS")
        print("FLIGHTS row count:", cur.fetchone()[0])
    finally:
        cur.close()
        con.close()
    print("Done. In .env set SNOWFLAKE_DATABASE=FLIGHTWISE and SNOWFLAKE_SCHEMA=PUBLIC (defaults).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
