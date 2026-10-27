import json

import pandas as pd
import pytest

from flightwise import config, llm
from flightwise.data import db, nl2sql
from flightwise.data.examples import EXAMPLES
from flightwise.data.guard import GuardError, check_sql

pytestmark = pytest.mark.skipif(not config.DUCKDB_PARQUET.exists(), reason="run scripts/fetch_bts.py first")


@pytest.fixture(autouse=True)
def duckdb_backend(monkeypatch):
    monkeypatch.setattr(config, "USE_SNOWFLAKE", False)
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "_backend", None)
    monkeypatch.setattr(db, "_schema_cache", None)


# ---- guard ----
@pytest.mark.parametrize("sql", [
    "DROP TABLE FLIGHTS",
    "DELETE FROM FLIGHTS",
    "INSERT INTO FLIGHTS SELECT * FROM FLIGHTS",
    "UPDATE FLIGHTS SET CARRIER='X'",
    "CREATE TABLE X AS SELECT * FROM FLIGHTS",
    "SELECT 1; SELECT 2",
    "SELECT * FROM FLIGHTS; DROP TABLE FLIGHTS",
    "SELECT * FROM other_table",
    "SELECT * FROM main.FLIGHTS",
    "SELECT * FROM read_csv('x.csv')",
    "SELECT * FROM FLIGHTS WHERE ORIGIN IN (SELECT a FROM secrets)",
    "COPY FLIGHTS TO 'x.csv'",
    "PRAGMA table_info('FLIGHTS')",
    "",
    "SELECT FROM WHERE ((",
])
def test_guard_rejects(sql):
    with pytest.raises(GuardError):
        check_sql(sql)


def test_guard_adds_and_clamps_limit():
    assert "LIMIT 500" in check_sql("SELECT * FROM FLIGHTS")
    assert "LIMIT 500" in check_sql("SELECT * FROM FLIGHTS LIMIT 100000")
    assert "LIMIT 10" in check_sql("SELECT * FROM flights LIMIT 10")
    assert "LIMIT 500" in check_sql("SELECT * FROM FLIGHTS LIMIT 10 OFFSET 5") or "LIMIT 10" in check_sql(
        "SELECT * FROM FLIGHTS LIMIT 10 OFFSET 5")


def test_guard_allows_cte_and_union():
    check_sql("WITH a AS (SELECT * FROM FLIGHTS) SELECT COUNT(*) FROM a")
    check_sql("SELECT 1 AS X FROM FLIGHTS UNION ALL SELECT 2 FROM FLIGHTS")
    assert check_sql("SELECT 1 AS X FROM FLIGHTS UNION ALL SELECT 2 FROM FLIGHTS").upper().endswith("LIMIT 500")


# ---- db ----
def test_backend_and_schema():
    assert db.backend_name() == "duckdb"
    s = db.get_schema()
    assert "DEP_DEL15" in s and "Top carriers" in s
    assert db.get_schema() is s  # cached
    assert len(s) < 4000


def test_snowflake_failure_falls_back(monkeypatch):
    monkeypatch.setattr(config, "USE_SNOWFLAKE", True)

    def boom():
        raise RuntimeError("no network")
    monkeypatch.setattr(db, "_connect_snowflake", boom)
    assert db.backend_name() == "duckdb"


# ---- examples ----
@pytest.mark.parametrize("q,sql", EXAMPLES, ids=[q[:30] for q, _ in EXAMPLES])
def test_example_runs(q, sql):
    df = db.run_query(check_sql(sql))
    assert len(df) > 0
    assert nl2sql.pick_chart(df) is not None or len(df) < 2


# ---- delay_risk ----
def test_delay_risk_real():
    r = nl2sql.delay_risk("aa", "dfw", hour=17)
    assert r.carrier == "AA" and r.origin == "DFW" and r.flights >= 30
    assert 0 <= r.pct_delayed_15 <= 100 and r.label in ("low", "medium", "high")
    assert "FROM FLIGHTS" in r.sql


def test_delay_risk_widens():
    r = nl2sql.delay_risk("AA", "OKC", hour=3, month=7)  # essentially no 3am AA flights
    assert r.hour is None or r.flights >= 30
    assert r.flights > 0


def test_delay_risk_unknown_route():
    r = nl2sql.delay_risk("ZZ", "QQQ", hour=1)
    assert r.flights == 0 and r.label == "unknown"


@pytest.mark.parametrize("pct,label", [(0, "low"), (19.9, "low"), (20, "medium"), (34.9, "medium"),
                                       (35, "high"), (80, "high"), (None, "unknown")])
def test_labels(pct, label):
    assert nl2sql.risk_label(pct) == label


def test_delay_risk_sql_escapes_quotes():
    assert "''" in nl2sql._risk_sql("A'B", "X", None, None)


# ---- chart rule ----
def test_chart_rule():
    c = nl2sql.pick_chart(pd.DataFrame({"DEP_HOUR": [1, 2, 3], "PCT": [1.0, 2.0, 3.0]}))
    assert (c.kind, c.x, c.y) == ("line", "DEP_HOUR", "PCT")
    c = nl2sql.pick_chart(pd.DataFrame({"CARRIER_NAME": ["a", "b"], "N": [1, 2], "M": [3, 4]}))
    assert (c.kind, c.x, c.y) == ("bar", "CARRIER_NAME", "N")
    c = nl2sql.pick_chart(pd.DataFrame({"MONTH": [6, 7], "N": [1, 2]}))
    assert c.kind == "line"
    c = nl2sql.pick_chart(pd.DataFrame({"FL_DATE": pd.to_datetime(["2026-07-01", "2026-07-02"]), "N": [1, 2]}))
    assert c.kind == "line"
    assert nl2sql.pick_chart(pd.DataFrame({"N": [1, 2], "M": [3, 4]})) is None
    assert nl2sql.pick_chart(pd.DataFrame({"A": ["x"], "N": [1]})) is None


# ---- ask() with mocked LLM ----
GOOD = EXAMPLES[0][1]


def _patch(monkeypatch, sqls, answer="Two sentences. Done."):
    calls = {"json": [], "chat": []}
    it = iter(sqls)

    def fake_json(messages, schema):
        calls["json"].append(messages)
        return {"sql": next(it)}

    def fake_chat(messages, **kw):
        calls["chat"].append(messages)
        return {"role": "assistant", "content": answer}
    monkeypatch.setattr(llm, "chat_json", fake_json)
    monkeypatch.setattr(llm, "chat", fake_chat)
    return calls


def test_ask_happy(monkeypatch):
    calls = _patch(monkeypatch, [GOOD])
    monkeypatch.setattr(nl2sql, "template_explain", lambda df: None)   # exercise the model path
    r = nl2sql.ask("best hour from OKC?")
    assert r.error is None and r.backend == "duckdb"
    assert r.columns[0] == "DEP_HOUR" and len(r.rows) > 5
    assert r.chart.kind == "line"
    assert r.answer == "Two sentences. Done."
    assert "LIMIT 500" in r.sql
    json.dumps(r.model_dump(mode="json"))  # JSON-safe
    assert len(calls["json"]) == 1 and len(calls["chat"]) == 1
    assert "DEP_DEL15" in calls["json"][0][0]["content"]  # schema in prompt


def test_ask_no_explain(monkeypatch):
    calls = _patch(monkeypatch, [GOOD])
    r = nl2sql.ask("q", explain=False)
    assert r.answer is None and not calls["chat"]


def test_ask_retry_on_sql_error(monkeypatch):
    calls = _patch(monkeypatch, ["SELECT NOPE FROM FLIGHTS", GOOD])
    r = nl2sql.ask("q")
    assert r.error is None and r.rows
    assert len(calls["json"]) == 2
    assert "failed" in calls["json"][1][-1]["content"]


def test_ask_retry_on_guard_error(monkeypatch):
    calls = _patch(monkeypatch, ["DROP TABLE FLIGHTS", GOOD])
    r = nl2sql.ask("q")
    assert r.error is None and len(calls["json"]) == 2


def test_ask_fails_twice(monkeypatch):
    _patch(monkeypatch, ["DELETE FROM FLIGHTS", "SELECT * FROM secrets"])
    r = nl2sql.ask("q")
    assert r.error and "secrets" in r.error and not r.rows


def test_ask_llm_down_never_raises(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("ollama down")
    monkeypatch.setattr(llm, "chat_json", boom)
    r = nl2sql.ask("q")
    assert r.error and "ollama down" in r.error


def test_ask_explain_failure_is_not_error(monkeypatch):
    _patch(monkeypatch, [GOOD])
    monkeypatch.setattr(nl2sql, "template_explain", lambda df: None)   # exercise the model path
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("x")))
    r = nl2sql.ask("q")
    assert r.error is None and r.answer is None and r.rows


def test_ask_explain_gets_at_most_50_rows(monkeypatch):
    calls = _patch(monkeypatch, ["SELECT FL_DATE, DEP_DELAY FROM FLIGHTS LIMIT 200"])
    monkeypatch.setattr(nl2sql, "template_explain", lambda df: None)   # exercise the model path
    r = nl2sql.ask("q")
    assert len(r.rows) == 200
    payload = calls["chat"][0][-1]["content"]
    assert len(json.loads(payload.split("Data: ", 1)[1])["rows"]) == 50


def test_snowflake_decimals_become_float():
    import decimal
    import pandas as pd
    from flightwise.data import db, nl2sql
    df = pd.DataFrame({"DEP_HOUR": [5, 6], "PCT_DELAYED": [decimal.Decimal("6.1"), decimal.Decimal("9.4")],
                       "FLIGHTS": [120, 340]})
    df = db._decimals_to_float(df)
    assert df["PCT_DELAYED"].dtype == float
    assert nl2sql.pick_chart(df).y == "PCT_DELAYED"


def test_template_explain_uses_exact_numbers():
    import pandas as pd
    from flightwise.data import nl2sql
    df = pd.DataFrame({"DEP_HOUR": [5, 6, 21], "PCT_DELAYED": [6.1, 9.4, 63.6], "FLIGHTS": [120, 340, 80]})
    text = nl2sql.template_explain(df)
    assert text == "5 AM has the lowest % delayed at 6.1%, and 9 PM the highest at 63.6%. 3 hours compared."
    assert nl2sql.template_explain(df.iloc[:0]) == "The query returned no rows."
    assert nl2sql.template_explain(pd.DataFrame({"A": ["x", "y"], "B": ["p", "q"]})) is None   # model fallback
