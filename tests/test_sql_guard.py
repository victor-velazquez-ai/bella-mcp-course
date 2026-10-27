import pytest

from bella_mcp.db import QueryError, check_shape, run_query

ATTACKS = [
    "DROP TABLE customers",
    "DELETE FROM orders",
    "UPDATE products SET stock_qty = 0",
    "INSERT INTO customers VALUES (999, 'x', 'x@x', 'SMB', 'x', 'x', '2026-01-01')",
    "SELECT 1; DROP TABLE customers",
    "WITH x AS (SELECT 1) DELETE FROM orders",
    "ATTACH DATABASE 'stolen.db' AS loot",
    "PRAGMA writable_schema = 1",
    "SELECT load_extension('evil.dll')",
    "SELECT length(randomblob(2000000000))",
    "",
]


@pytest.mark.parametrize("sql", ATTACKS)
def test_attacks_are_blocked(db_path, sql):
    with pytest.raises(QueryError):
        run_query(db_path, sql)


def test_the_database_survives(db_path):
    assert run_query(db_path, "SELECT COUNT(*) AS n FROM customers").rows[0]["n"] == 320


def test_infinite_query_times_out(db_path):
    with pytest.raises(QueryError, match="stopped"):
        run_query(db_path, "WITH RECURSIVE r(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM r) SELECT count(*) FROM r",
                  timeout_ms=300)


def test_row_cap(db_path):
    result = run_query(db_path, "SELECT * FROM order_items", max_rows=50)
    assert len(result.rows) == 50 and result.truncated


@pytest.mark.parametrize("sql", [
    "SELECT email FROM customers LIMIT 5",
    "SELECT e FROM (SELECT email AS e FROM customers) LIMIT 5",
    "SELECT group_concat(email) AS e FROM customers",
    "SELECT upper(email) AS e FROM sales_reps",
])
def test_pii_is_masked_without_scope(db_path, sql):
    result = run_query(db_path, sql)
    assert all(v is None for row in result.rows for v in row.values())
    assert result.redacted_columns


def test_pii_cannot_be_probed(db_path):
    assert run_query(db_path, "SELECT count(*) AS n FROM customers WHERE email LIKE '%@%'").rows[0]["n"] == 0


def test_pii_visible_with_scope(db_path):
    result = run_query(db_path, "SELECT email FROM customers LIMIT 1", allow_pii=True)
    assert "@" in result.rows[0]["email"] and not result.redacted_columns


@pytest.mark.parametrize("sql", ["SELECT 1", "  select 1 ;", "-- comment\nSELECT 1", "WITH a AS (SELECT 1) SELECT * FROM a"])
def test_valid_shapes(sql):
    assert check_shape(sql)
