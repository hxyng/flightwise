"""Natural-language question -> SQL -> guard -> run -> chart -> explanation. Never raises."""
from __future__ import annotations

import datetime as dt
import decimal
import json
import logging
import math

import pandas as pd

from .. import llm
from ..models import DelayRisk, QueryResult
from . import db
from .examples import EXAMPLES
from .guard import GuardError, check_sql  # noqa: F401  (check_sql re-exported for the contract)
from .summary import pick_chart, template_explain  # noqa: F401  (re-exported)

log = logging.getLogger(__name__)

SQL_SCHEMA = {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}
MAX_EXPLAIN_ROWS = 50


def _system_prompt() -> str:
    ex = "\n\n".join(f"Q: {q}\nSQL: {s}" for q, s in EXAMPLES)
    return (
        "You write one SQL query that answers a question about US flight on-time performance.\n"
        "Rules: output a single SELECT (or WITH ... SELECT) over the table FLIGHTS only. Use only columns "
        "listed below, standard SQL that runs on both DuckDB and Snowflake (no vendor-specific functions). "
        "Use ROUND(...,1) for percentages and averages, and give columns short UPPER_SNAKE aliases. "
        "Delay rate = 100.0 * AVG(DEP_DEL15). Put the category or time column first and the measure second. "
        "Filter small samples with HAVING COUNT(*) >= 30 when grouping. Airports and carriers are IATA codes "
        "in upper case. Return JSON {\"sql\": \"...\"}.\n\n"
        f"{db.get_schema()}\n\nExamples:\n{ex}"
    )


def _json_safe(v):
    if v is None:
        return None
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.datetime, dt.date, pd.Timestamp)):
        return None if v is pd.NaT else v.isoformat()
    if isinstance(v, (str, bool, int)):
        return v
    if hasattr(v, "item"):  # numpy scalar
        return _json_safe(v.item())
    return str(v)


def _rows(df: pd.DataFrame) -> list[list]:
    return [[_json_safe(None if pd.isna(v) is True else v) for v in row] for row in df.itertuples(index=False, name=None)]


def _generate(messages: list[dict]) -> str:
    out = llm.chat_json(messages, SQL_SCHEMA)
    sql = out.get("sql") if isinstance(out, dict) else None
    if not isinstance(sql, str) or not sql.strip():
        raise GuardError("model returned no SQL")
    return sql.strip()


def _explain(question: str, df: pd.DataFrame) -> str | None:
    if text := template_explain(df):
        return text
    data = df.head(MAX_EXPLAIN_ROWS)
    payload = json.dumps({"columns": list(data.columns), "rows": _rows(data)})
    msgs = [
        {"role": "system", "content": "You explain flight-delay query results in exactly two plain sentences. "
                                      "Use only numbers that appear in the data. Percent columns are percentages. "
                                      "Do not mention SQL or columns."},
        {"role": "user", "content": f"Question: {question}\nData: {payload}"},
    ]
    try:
        text = (llm.chat(msgs).get("content") or "").strip()
        return text or None
    except Exception as e:  # noqa: BLE001 - explanation is optional
        log.warning("explain failed: %s", e)
        return None


def ask(question: str, explain: bool = True) -> QueryResult:
    res = QueryResult(question=question)
    try:
        res.backend = db.backend_name()
        messages = [{"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": question}]
        sql, df, last_err = None, None, None
        for attempt in range(2):
            try:
                sql = _generate(messages)
                res.sql = sql
                safe = check_sql(sql)
                res.sql = safe
                df = db.run_query(safe)
                last_err = None
                break
            except Exception as e:  # noqa: BLE001 - guard, SQL and LLM errors all get one retry
                last_err = f"{type(e).__name__}: {e}"
                log.info("ask attempt %d failed: %s", attempt + 1, last_err)
                if attempt == 0 and sql:
                    messages += [
                        {"role": "assistant", "content": json.dumps({"sql": sql})},
                        {"role": "user", "content": f"That SQL failed: {str(e)[:500]}\n"
                                                    "Fix it and return corrected JSON {\"sql\": \"...\"}."},
                    ]
                elif attempt == 0:
                    messages.append({"role": "user", "content": f"Error: {str(e)[:300]}. Return JSON {{\"sql\": ...}}."})
        if last_err or df is None:
            res.error = last_err or "query failed"
            return res
        res.columns = [str(c) for c in df.columns]
        res.rows = _rows(df)
        res.chart = pick_chart(df)
        if explain:
            res.answer = _explain(question, df) if len(df) else "The query returned no rows."
    except Exception as e:  # noqa: BLE001 - ask() never raises
        log.exception("ask failed")
        res.error = f"{type(e).__name__}: {e}"
    return res


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _risk_sql(carrier: str, origin: str, hour: int | None, month: int | None) -> str:
    where = [f"CARRIER = {_lit(carrier)}", f"ORIGIN = {_lit(origin)}"]
    if hour is not None:
        where.append(f"DEP_HOUR = {int(hour)}")
    if month is not None:
        where.append(f"MONTH = {int(month)}")
    return ("SELECT COUNT(*) AS FLIGHTS, ROUND(100.0 * AVG(DEP_DEL15), 1) AS PCT_DELAYED_15, "
            "ROUND(AVG(DEP_DELAY), 1) AS AVG_DEP_DELAY, ROUND(100.0 * AVG(CANCELLED), 2) AS PCT_CANCELLED "
            "FROM FLIGHTS WHERE " + " AND ".join(where))


def risk_label(pct: float | None) -> str:
    if pct is None:
        return "unknown"
    return "low" if pct < 20 else "medium" if pct < 35 else "high"


def delay_risk(carrier: str, origin: str, hour: int | None = None, month: int | None = None) -> DelayRisk:
    """Fixed SQL, no LLM. Widens (drop hour, then month) when fewer than 30 flights match;
    the returned hour/month are the filters actually used."""
    carrier, origin = carrier.strip().upper(), origin.strip().upper()
    attempts = [(hour, month)]
    if hour is not None:
        attempts.append((None, month))
    if month is not None:
        attempts.append((None, None))
    best = None
    for h, m in attempts:
        sql = _risk_sql(carrier, origin, h, m)
        row = db.run_query(sql).iloc[0]
        n = int(row["FLIGHTS"])
        best = (h, m, sql, n, row)
        if n >= 30:
            break
    h, m, sql, n, row = best

    def f(k: str) -> float:
        v = row[k]
        return 0.0 if pd.isna(v) else float(v)

    pct = f("PCT_DELAYED_15") if n else None
    return DelayRisk(carrier=carrier, origin=origin, hour=h, month=m, flights=n,
                     pct_delayed_15=f("PCT_DELAYED_15"), avg_dep_delay=f("AVG_DEP_DELAY"),
                     pct_cancelled=f("PCT_CANCELLED"), label=risk_label(pct), sql=sql)
