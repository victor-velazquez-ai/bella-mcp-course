"""Build (or rebuild) Brightline Outdoor's demo database.

Run:  python data/seed.py
"""

import sqlite3
import sys

from bella_mcp.config import Settings
from bella_mcp.seed import build_database

if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    path = build_database(Settings().db_path)
    conn = sqlite3.connect(path)
    for table in ("customers", "products", "sales_reps", "orders", "order_items"):
        print(f"  {table:<12} {conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:>6} rows")
    revenue = conn.execute("SELECT ROUND(SUM(revenue)) FROM sales").fetchone()[0]
    print(f"  revenue (completed + shipped): ${revenue:,.0f}")
    print(f"Built {path}")
