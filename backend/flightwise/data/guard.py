"""SQL guard: one read-only SELECT over FLIGHTS, capped at 500 rows."""
from __future__ import annotations

import sqlglot
from sqlglot import exp

MAX_ROWS = 500
ALLOWED_TABLE = "FLIGHTS"


class GuardError(ValueError):
    """The SQL violates the read-only / FLIGHTS-only policy."""


_FORBIDDEN = tuple(
    getattr(exp, n) for n in (
        "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "Command", "Copy",
        "Use", "Set", "Transaction", "Commit", "Rollback", "Into", "Pragma", "Attach", "Detach",
    ) if hasattr(exp, n)
)


def check_sql(sql: str) -> str:
    """Return the vetted SQL (with LIMIT <= 500) or raise GuardError."""
    if not sql or not sql.strip():
        raise GuardError("empty SQL")
    try:
        stmts = [s for s in sqlglot.parse(sql) if s is not None]
    except sqlglot.errors.SqlglotError as e:
        raise GuardError(f"could not parse SQL: {str(e)[:200]}") from e
    if len(stmts) != 1:
        raise GuardError("exactly one SQL statement is allowed")
    tree = stmts[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)):
        raise GuardError("only SELECT / WITH queries are allowed")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN):
            raise GuardError(f"{type(node).__name__} is not allowed")
    ctes = {c.alias.upper() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            raise GuardError("table functions are not allowed; query FLIGHTS only")
        if t.args.get("db") or t.args.get("catalog"):
            raise GuardError("qualified table names are not allowed; use FLIGHTS")
        name = t.name.upper()
        if name != ALLOWED_TABLE and name not in ctes:
            raise GuardError(f"table {t.name!r} is not allowed; only FLIGHTS")
    if isinstance(tree, exp.Subquery):
        tree = tree.unnest()
    lim = tree.args.get("limit")
    cur = None
    if lim is not None and isinstance(lim.expression, exp.Literal) and lim.expression.is_int:
        cur = int(lim.expression.name)
    if cur is None or cur > MAX_ROWS:
        tree = tree.limit(MAX_ROWS)
    return tree.sql()
