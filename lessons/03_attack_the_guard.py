"""Lesson 3 — attack the guard.

An AI that can run SQL is an AI that can be TOLD to run SQL — by a user, by a prompt
injection hidden in a document, or by its own mistake. So we don't trust the SQL;
we trust the guard (src/bella_mcp/db.py). Here we throw real attacks at it.

    python lessons/03_attack_the_guard.py
"""

import sys

from bella_mcp.config import Settings
from bella_mcp.db import QueryError, run_query
from bella_mcp.seed import ensure_database

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

DB = ensure_database(Settings().db_path)

# (attack, what it tries)
ATTACKS = [
    ("DROP TABLE customers", "destroy data"),
    ("SELECT 1; DROP TABLE customers", "smuggle a 2nd statement"),
    ("WITH x AS (SELECT 1) DELETE FROM orders", "hide a DELETE behind WITH"),
    ("ATTACH DATABASE 'stolen.db' AS loot", "write a copy elsewhere"),
    ("PRAGMA writable_schema = 1", "tamper with the schema"),
    ("SELECT load_extension('evil.dll')", "load native code"),
    ("SELECT length(randomblob(2000000000))", "exhaust memory"),
    ("WITH RECURSIVE r(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM r) SELECT count(*) FROM r", "infinite loop"),
]
# PII probes: these "succeed" but must return no personal data
PII_PROBES = [
    "SELECT name, email FROM customers LIMIT 3",
    "SELECT e FROM (SELECT email AS e FROM customers) LIMIT 3",
    "SELECT group_concat(email) AS emails FROM customers",
    "SELECT count(*) AS hits FROM customers WHERE email LIKE '%@%'",
]


def main() -> int:
    failures = 0
    print("Attacks (a viewer/analyst role, no bella:pii):\n")
    for sql, intent in ATTACKS:
        try:
            run_query(DB, sql, timeout_ms=1000)
            print(f"  ❌ NOT BLOCKED  {intent:<26} {sql}")
            failures += 1
        except QueryError as exc:
            print(f"  ✅ blocked      {intent:<26} → {exc}")

    print("\nPII probes (allowed to run, but emails must come back empty):\n")
    for sql in PII_PROBES:
        result = run_query(DB, sql)
        values = [v for row in result.rows for v in row.values()]
        leaked = any(isinstance(v, str) and "@" in v for v in values) or (result.rows and result.rows[0].get("hits"))
        print(f"  {'❌ LEAK' if leaked else '✅ masked'}  {sql}\n      → {result.rows[:2]}  redacted={result.redacted_columns}")
        failures += bool(leaked)

    print("\nSame question as an admin (bella:pii) — now the email is visible:")
    print("  ", run_query(DB, "SELECT name, email FROM customers LIMIT 1", allow_pii=True).rows)

    big = run_query(DB, "SELECT * FROM order_items")
    print(f"\nRow cap: 'SELECT * FROM order_items' returned {len(big.rows)} rows, truncated={big.truncated}")

    print(f"\n{'All attacks blocked.' if not failures else f'{failures} attack(s) got through!'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
