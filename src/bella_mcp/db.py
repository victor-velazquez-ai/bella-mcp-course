"""The data layer — and the most important security code in the repo.

Every query Bella runs goes through `run_query()`: the 4 preset tools, the SQL that
Bella's brain writes, and raw SQL sent by the client. One door, many locks:

  layer 2  shape check    exactly one SELECT / WITH statement
  layer 3  read-only      SQLite opened with mode=ro: writes are impossible
  layer 4  authorizer     SQLite asks us about EVERY table/column/action at compile
                          time: we allow reads only, and blank out PII columns
                          (customers.email, sales_reps.email) unless the caller
                          holds bella:pii — aliases or tricks can't get around it
  layer 5  limits         row cap + query timeout + max string size

(Layer 1 — scopes — lives in auth.py; layer 6 — audit — in audit.py.)
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PII_COLUMNS = {("customers", "email"), ("sales_reps", "email")}

_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),  # WITH RECURSIVE
}
_LEADING_COMMENTS = re.compile(r"^\s*(--[^\n]*\n|/\*.*?\*/)\s*", re.DOTALL)


class QueryError(Exception):
    """A problem the caller (usually an LLM) can fix — the message says how."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool
    elapsed_ms: int
    redacted_columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"columns": self.columns, "rows": self.rows, "row_count": len(self.rows)}
        if self.truncated:
            out["truncated"] = True
            out["note"] = f"Only the first {len(self.rows)} rows are shown. Aggregate or add filters for complete answers."
        if self.redacted_columns:
            out["redacted_columns"] = self.redacted_columns
            out["privacy_note"] = "Personal data (emails) is hidden for your role; it requires the bella:pii scope."
        return out


def check_shape(sql: str) -> str:
    """Layer 2: one read statement. Returns the cleaned SQL or raises QueryError."""
    cleaned = sql.strip().rstrip(";").strip()
    head = cleaned
    while (m := _LEADING_COMMENTS.match(head)) is not None:
        head = head[m.end():]
    first_word = head.split(None, 1)[0].upper() if head else ""
    if first_word not in {"SELECT", "WITH"}:
        raise QueryError("Bella only runs read-only queries: send a single SELECT (or WITH ... SELECT) statement.")
    return cleaned


def run_query(
    db_path: Path,
    sql: str,
    params: tuple | dict = (),
    *,
    allow_pii: bool = False,
    max_rows: int = 200,
    timeout_ms: int = 2000,
) -> QueryResult:
    sql = check_shape(sql)
    redacted: set[str] = set()

    def authorizer(action: int, arg1: str | None, arg2: str | None, _db: str | None, _source: str | None) -> int:
        if action not in _ALLOWED_ACTIONS:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ and (arg1, arg2) in PII_COLUMNS and not allow_pii:
            redacted.add(f"{arg1}.{arg2}")
            return sqlite3.SQLITE_IGNORE  # the column reads as NULL
        return sqlite3.SQLITE_OK

    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)  # layer 3
    try:
        conn.row_factory = sqlite3.Row
        conn.set_authorizer(authorizer)  # layer 4
        if hasattr(conn, "setlimit"):  # Python 3.11+: cap strings/blobs at 1 MB
            conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
        started = time.perf_counter()
        deadline = started + timeout_ms / 1000
        conn.set_progress_handler(lambda: int(time.perf_counter() > deadline), 1_000)  # layer 5
        cursor = conn.execute(sql, params)
        fetched = cursor.fetchmany(max_rows + 1)
        columns = [d[0] for d in cursor.description or []]
        elapsed_ms = int((time.perf_counter() - started) * 1000)
    except sqlite3.ProgrammingError as exc:
        if "one statement" in str(exc):
            raise QueryError("Send exactly one SQL statement (no ';' separated batches).") from None
        raise QueryError(f"Invalid query: {exc}") from None
    except sqlite3.DatabaseError as exc:
        raise QueryError(_explain(str(exc), timeout_ms)) from None
    finally:
        conn.close()

    rows = [dict(r) for r in fetched[:max_rows]]
    return QueryResult(columns, rows, len(fetched) > max_rows, elapsed_ms, sorted(redacted))


def _explain(message: str, timeout_ms: int) -> str:
    """Turn SQLite errors into instructions the model can act on."""
    lower = message.lower()
    if "not authorized" in lower:
        return "Blocked by Bella's guard: only reads are allowed (no PRAGMA, ATTACH, INSERT, UPDATE, DELETE or DDL)."
    if "interrupted" in lower:
        return f"Query stopped after {timeout_ms} ms. Aggregate, filter by date, or add a LIMIT."
    if "too big" in lower:
        return "A value in the result is too large (1 MB limit). Select fewer or smaller columns."
    if "readonly" in lower or "read-only" in lower:
        return "The database is read-only."
    return f"SQL error: {message}. Check table and column names in the bella://schema resource."


def schema_markdown(db_path: Path) -> str:
    """The schema + business glossary, for the bella://schema resource and Bella's brain."""
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        info = dict(conn.execute("SELECT key, value FROM dataset_info").fetchall())
        lines = [
            f"# {info.get('company', 'Database')} — schema",
            f"Data from {info.get('data_from')} to {info.get('as_of_date')} (treat {info.get('as_of_date')} as today). "
            f"Currency: {info.get('currency', 'USD')}. Dates are ISO strings 'YYYY-MM-DD'. SQL dialect: SQLite.",
            "",
        ]
        objects = conn.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') AND name != 'dataset_info' ORDER BY type, name"
        ).fetchall()
        for name, kind in objects:
            cols = conn.execute(f"PRAGMA table_info({name})").fetchall()
            col_list = ", ".join(f"{c[1]} {c[2]}".strip() for c in cols)
            lines.append(f"- **{name}** ({kind}): {col_list}")
    finally:
        conn.close()
    lines += [
        "",
        "## Business glossary (use these definitions)",
        "- **Revenue** = SUM(sales.revenue). The `sales` view already applies the rules: only 'completed' and 'shipped' "
        "orders count, net of line discounts. Always use the `sales` view for revenue, margin, units and AOV.",
        "- **Margin %** = SUM(margin) / SUM(revenue) * 100.",
        "- **Orders** = COUNT(DISTINCT order_id). **AOV** (average order value) = SUM(revenue) / COUNT(DISTINCT order_id).",
        "- **Active customer** = at least one revenue-recognised order in the last 180 days.",
        "- **Inventory alert** = products.stock_qty <= products.reorder_level.",
        "- Statuses: completed, shipped (revenue) · pending (not yet revenue) · cancelled, refunded (never revenue).",
        "- **Region** comes from the sales rep (sales.region / sales_reps.region).",
        "- Emails are personal data: they read as NULL unless the caller has the bella:pii scope.",
    ]
    return "\n".join(lines)
