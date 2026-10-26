"""Download BTS On-Time Performance monthly zips and build data/flights.parquet.

Usage (from backend/):  python scripts/fetch_bts.py [--year 2026] [--months 6 7 8]
A month that 404s falls back to the previous month (once per requested month).
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import duckdb
import httpx

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
URL = ("https://www.transtats.bts.gov/PREZIP/"
       "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{y}_{m}.zip")

CARRIERS = {
    "AA": "American Airlines", "DL": "Delta Air Lines", "UA": "United Airlines",
    "WN": "Southwest Airlines", "AS": "Alaska Airlines", "B6": "JetBlue Airways",
    "NK": "Spirit Airlines", "F9": "Frontier Airlines", "G4": "Allegiant Air",
    "HA": "Hawaiian Airlines", "OO": "SkyWest Airlines", "YX": "Republic Airways",
    "MQ": "Envoy Air", "9E": "Endeavor Air", "OH": "PSA Airlines", "QX": "Horizon Air",
    "YV": "Mesa Airlines", "C5": "CommuteAir", "ZW": "Air Wisconsin", "G7": "GoJet Airlines",
    "EV": "ExpressJet", "SY": "Sun Country Airlines", "MX": "Breeze Airways",
}


def download(y: int, m: int, dest: Path) -> bool:
    url = URL.format(y=y, m=m)
    with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
        if r.status_code == 404:
            return False
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--months", type=int, nargs="+", default=[6, 7, 8])
    a = ap.parse_args()
    raw = DATA / "_raw"
    raw.mkdir(parents=True, exist_ok=True)
    csvs: list[Path] = []
    used: set[tuple[int, int]] = set()
    for m in a.months:
        y, mm = a.year, m
        while True:
            if (y, mm) in used:
                mm -= 1
                continue
            z = raw / f"{y}_{mm}.zip"
            print(f"downloading {y}-{mm:02d} ...", flush=True)
            if download(y, mm, z):
                break
            print(f"  404, trying previous month", flush=True)
            mm -= 1
            if mm == 0:
                y, mm = y - 1, 12
        used.add((y, mm))
        with zipfile.ZipFile(z) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            out = raw / f"{y}_{mm}.csv"   # short name: Windows MAX_PATH
            with zf.open(name) as src, open(out, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            csvs.append(out)
        z.unlink()

    con = duckdb.connect()
    cmap = ", ".join(f"('{k}','{v}')" for k, v in CARRIERS.items())
    con.execute(f"CREATE TABLE cmap AS SELECT * FROM (VALUES {cmap}) t(code, name)")
    files = ", ".join(f"'{c.as_posix()}'" for c in csvs)
    con.execute(f"""
      CREATE TABLE flights AS
      SELECT
        CAST(FlightDate AS DATE) AS FL_DATE,
        CAST(Month AS INTEGER) AS MONTH,
        CAST(DayOfWeek AS INTEGER) AS DAY_OF_WEEK,
        Reporting_Airline AS CARRIER,
        COALESCE(c.name, Reporting_Airline) AS CARRIER_NAME,
        CAST(Flight_Number_Reporting_Airline AS INTEGER) AS FLIGHT_NUM,
        Origin AS ORIGIN, OriginCityName AS ORIGIN_CITY,
        Dest AS DEST, DestCityName AS DEST_CITY,
        CAST(CRSDepTime AS INTEGER) AS CRS_DEP_TIME,
        CAST(CRSDepTime AS INTEGER) // 100 % 24 AS DEP_HOUR,
        CAST(DepDelay AS DOUBLE) AS DEP_DELAY,
        CAST(DepDel15 AS INTEGER) AS DEP_DEL15,
        CAST(ArrDelay AS DOUBLE) AS ARR_DELAY,
        CAST(ArrDel15 AS INTEGER) AS ARR_DEL15,
        CAST(Cancelled AS INTEGER) AS CANCELLED,
        CancellationCode AS CANCELLATION_CODE,
        CAST(Distance AS DOUBLE) AS DISTANCE,
        CAST(CarrierDelay AS DOUBLE) AS CARRIER_DELAY,
        CAST(WeatherDelay AS DOUBLE) AS WEATHER_DELAY,
        CAST(NASDelay AS DOUBLE) AS NAS_DELAY,
        CAST(LateAircraftDelay AS DOUBLE) AS LATE_AIRCRAFT_DELAY
      FROM read_csv([{files}], header=true, ignore_errors=true, sample_size=-1) f
      LEFT JOIN cmap c ON c.code = f.Reporting_Airline
      WHERE Diverted = 0 OR Diverted IS NULL
    """)
    con.execute(f"COPY flights TO '{(DATA / 'flights.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f"COPY flights TO '{(DATA / 'flights.csv.gz').as_posix()}' (FORMAT CSV, HEADER, COMPRESSION GZIP)")
    n = con.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
    print("rows:", n, "months:", con.execute("SELECT DISTINCT MONTH FROM flights ORDER BY 1").fetchall())
    for c in csvs:
        c.unlink(missing_ok=True)
    try:
        raw.rmdir()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
