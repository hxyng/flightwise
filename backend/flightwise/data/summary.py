"""Pure-pandas summaries of query results: the chart rule and the templated explanation.
No model or database calls, so the cache, the agent's answer templates and nl2sql can all use it."""
from __future__ import annotations

import re

import pandas as pd

from ..models import ChartSpec

_ORDINAL_X = re.compile(r"(^|_)(HOUR|MONTH|DATE|DAY|YEAR|WEEK|TIME|DOW|WEEKDAY)($|_)")
_LINE_X = re.compile(r"(^|_)(HOUR|MONTH|DATE|YEAR|TIME)($|_)")


def pick_chart(df: pd.DataFrame) -> ChartSpec | None:
    """x = first non-numeric or ordinal-named column, y = first other numeric column.
    Time-like x (hour/month/date/year) -> line, otherwise bar."""
    if len(df) < 2 or df.shape[1] < 2:
        return None
    cols = list(df.columns)
    numeric = {c for c in cols if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])}
    x = next((c for c in cols if c not in numeric or _ORDINAL_X.search(str(c).upper())), None)
    if x is None:
        return None
    y = next((c for c in cols if c in numeric and c != x), None)
    if y is None:
        return None
    kind = "line" if (_LINE_X.search(str(x).upper()) or pd.api.types.is_datetime64_any_dtype(df[x])) else "bar"
    return ChartSpec(kind=kind, x=str(x), y=str(y))


_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
_DAYS = ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]   # BTS: 1 = Monday


def _label(col: str, v) -> str:
    """Human label for an x value: hours, months and BTS weekdays get names."""
    c = col.upper()
    try:
        n = int(v)
    except (TypeError, ValueError):
        return str(v)
    if "HOUR" in c and 0 <= n <= 23:
        return f"{n % 12 or 12} {'AM' if n < 12 else 'PM'}"
    if c == "MONTH" and 1 <= n <= 12:
        return _MONTHS[n]
    if ("DAY_OF_WEEK" in c or c in ("DOW", "WEEKDAY")) and 1 <= n <= 7:
        return _DAYS[n]
    return str(v)


def _measure(col: str, v: float) -> str:
    c = col.upper()
    if "PCT" in c or "RATE" in c or "PERCENT" in c:
        return f"{v:.1f}%"
    if "DELAY" in c and "MIN" not in c and abs(v) < 1000:
        return f"{v:.1f} min"
    return f"{v:,.0f}" if float(v).is_integer() or abs(v) >= 100 else f"{v:.1f}"


def _words(col: str) -> str:
    c = col.upper().replace("PCT_", "% ").replace("_PCT", " %").replace("AVG_", "average ")
    return c.replace("_", " ").lower().strip()


def template_explain(df: pd.DataFrame) -> str | None:
    """Two-sentence summary computed from the rows (exact numbers, no model call).
    Returns None for shapes it doesn't cover, so the caller can fall back to the model."""
    if df.empty:
        return "The query returned no rows."
    chart = pick_chart(df)
    if len(df) == 1:
        parts = [f"{_words(c)} {_measure(c, v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v}"
                 for c, v in df.iloc[0].items() if v is not None]
        return ("Result: " + ", ".join(parts) + ".") if parts else None
    if chart is None:
        return None
    x, y = chart.x, chart.y
    data = df[[x, y]].dropna()
    if len(data) < 2:
        return None
    lo, hi = data.loc[data[y].idxmin()], data.loc[data[y].idxmax()]
    what = _words(y)
    return (f"{_label(x, lo[x])} has the lowest {what} at {_measure(y, lo[y])}, and "
            f"{_label(x, hi[x])} the highest at {_measure(y, hi[y])}. "
            f"{len(data)} {_plural(x)} compared.")


def _plural(col: str) -> str:
    c = col.upper()
    for key, noun in (("HOUR", "hours"), ("MONTH", "months"), ("DAY", "days"), ("DATE", "days"),
                      ("CARRIER", "airlines"), ("AIRLINE", "airlines"), ("ROUTE", "routes"),
                      ("ORIGIN", "airports"), ("DEST", "airports"), ("CAUSE", "causes")):
        if key in c:
            return noun
    return "groups"
