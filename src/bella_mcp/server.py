"""Bella — Brightline Outdoor's AI data analyst, exposed over MCP.

5 tools (4 presets + 1 general query), 1 resource, 1 prompt, 1 health route.

    build_server(settings) -> FastMCP

A factory instead of a module-level `mcp = FastMCP(...)`: the same code builds a
local stdio server, a JWT-protected HTTP server, or an OAuth server for claude.ai,
and tests can build one of each side by side.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import __version__
from .audit import AuditMiddleware
from .auth import PII, QUERY, READ, Permissions, build_auth
from .brain import Brain, BrainUnavailable
from .config import Settings
from .db import QueryError, QueryResult, run_query, schema_markdown
from .seed import ensure_database

INSTRUCTIONS = """You are connected to Bella, the data analyst of Brightline Outdoor (an outdoor-gear retailer).
Data: customers, products, orders and sales reps from 2025-01-01 to 2026-09-30; treat 2026-09-30 as today.
Prefer the preset tools — they encode the official business definitions:
  sales_summary (revenue/orders/margin over time or by dimension), top_customers,
  inventory_alerts (stock at risk), customer_profile (one customer, 360° view).
For any other question use ask_bella: send plain English, or a read-only SQL SELECT (schema: bella://schema).
Always state the period and filters you used. Emails are hidden unless the user holds the bella:pii scope."""

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

GroupBy = Literal["month", "category", "region", "channel"]
Segment = Literal["Consumer", "SMB", "Enterprise"]
Category = Literal["Tents", "Backpacks", "Footwear", "Apparel", "Climbing", "Camp Kitchen"]
DateStr = Annotated[str | None, Field(description="Inclusive date, YYYY-MM-DD. Omit for no limit.")]

# Anything that starts like SQL is treated as SQL (and then judged by the guard), so
# "DROP TABLE customers" is rejected instead of being "interpreted" by the brain.
_SQL_START = re.compile(
    r"^\s*(--|/\*|(select|insert|update|delete|drop|alter|create|replace|pragma|attach|detach|vacuum)\b"
    r"|with\s+(recursive\s+)?\w+\s+as\s*\()",
    re.IGNORECASE,
)


def build_server(settings: Settings | None = None) -> FastMCP:
    settings = settings or Settings()
    ensure_database(settings.db_path)
    perms = Permissions(settings)
    brain = Brain()
    schema = schema_markdown(settings.db_path)

    mcp = FastMCP(
        "Bella",
        instructions=INSTRUCTIONS,
        version=__version__,
        auth=build_auth(settings),
        mask_error_details=True,  # unexpected exceptions never leak internals to the client
        middleware=[
            AuditMiddleware(settings.audit_log_path, who=lambda: perms.caller().name),
            RateLimitingMiddleware(
                max_requests_per_second=settings.rate_limit_per_second,
                burst_capacity=int(settings.rate_limit_per_second * 4),
                get_client_id=lambda _ctx: perms.caller().name,
            ),
        ],
    )

    def query(sql: str, params: dict[str, Any] | None = None) -> QueryResult:
        """The single door to the database. Raises ToolError so the model can self-correct."""
        try:
            return run_query(
                settings.db_path, sql, params or {},
                allow_pii=perms.has(PII), max_rows=settings.max_rows, timeout_ms=settings.query_timeout_ms,
            )
        except QueryError as exc:
            raise ToolError(str(exc)) from None

    # ------------------------------------------------------------------ preset 1
    @mcp.tool(annotations=READ_ONLY, auth=perms.require(READ))
    def sales_summary(group_by: GroupBy = "month", start_date: DateStr = None, end_date: DateStr = None) -> dict:
        """Revenue, orders, units, average order value and margin %, grouped by month, category, region or channel.

        Uses the official revenue definition (completed + shipped orders, net of discounts).
        Example: "how did revenue evolve this year?" -> group_by="month", start_date="2026-01-01".
        """
        start, end = _date(start_date, "start_date"), _date(end_date, "end_date")
        result = query(
            f"""SELECT {group_by}, ROUND(SUM(revenue), 2) AS revenue, COUNT(DISTINCT order_id) AS orders,
                       SUM(quantity) AS units, ROUND(SUM(revenue) / COUNT(DISTINCT order_id), 2) AS avg_order_value,
                       ROUND(100 * SUM(margin) / SUM(revenue), 1) AS margin_pct
                FROM sales
                WHERE order_date >= COALESCE(:start, '0000') AND order_date <= COALESCE(:end, '9999')
                GROUP BY {group_by}
                ORDER BY {"month" if group_by == "month" else "revenue DESC"}""",
            # group_by is safe to place in SQL: the Literal type means FastMCP rejects anything
            # outside the 4 allowed values before this code runs. User VALUES always go as parameters.
            {"start": start, "end": end},
        )
        totals = {
            "revenue": round(sum(r["revenue"] for r in result.rows), 2),
            "orders": sum(r["orders"] for r in result.rows),
        }
        return {"group_by": group_by, "period": {"start": start or "2025-01-01", "end": end or "2026-09-30"},
                "totals": totals, **result.to_dict()}

    # ------------------------------------------------------------------ preset 2
    @mcp.tool(annotations=READ_ONLY, auth=perms.require(READ))
    def top_customers(
        limit: Annotated[int, Field(ge=1, le=50, description="How many customers to return (1-50).")] = 10,
        start_date: DateStr = None,
        end_date: DateStr = None,
        segment: Segment | None = None,
    ) -> dict:
        """The customers who generated the most revenue in a period, with order count and last order date.

        Optionally filter by segment (Consumer, SMB, Enterprise). Emails are only shown to roles with bella:pii.
        """
        start, end = _date(start_date, "start_date"), _date(end_date, "end_date")
        result = query(
            """SELECT c.customer_id, c.name, c.segment, c.country, c.email AS email,
                      ROUND(SUM(s.revenue), 2) AS revenue, COUNT(DISTINCT s.order_id) AS orders,
                      MAX(s.order_date) AS last_order
               FROM sales s JOIN customers c ON c.customer_id = s.customer_id
               WHERE s.order_date >= COALESCE(:start, '0000') AND s.order_date <= COALESCE(:end, '9999')
                 AND (:segment IS NULL OR c.segment = :segment)
               GROUP BY c.customer_id
               ORDER BY revenue DESC
               LIMIT :limit""",
            {"start": start, "end": end, "segment": segment, "limit": limit},
        )
        return {"period": {"start": start or "2025-01-01", "end": end or "2026-09-30"}, "segment": segment,
                **result.to_dict()}

    # ------------------------------------------------------------------ preset 3
    @mcp.tool(annotations=READ_ONLY, auth=perms.require(READ))
    def inventory_alerts(category: Category | None = None) -> dict:
        """Products at or below their reorder level, most urgent first.

        For each: stock, reorder level, units sold in the last 90 days, days of cover left at that pace,
        and a suggested reorder quantity (enough for ~45 days, at least 2x the reorder level).
        """
        result = query(
            """WITH velocity AS (
                   SELECT product_id, SUM(quantity) AS units_90d FROM sales
                   WHERE order_date > date((SELECT value FROM dataset_info WHERE key = 'as_of_date'), '-90 days')
                   GROUP BY product_id)
               SELECT p.sku, p.name, p.category, p.stock_qty, p.reorder_level,
                      COALESCE(v.units_90d, 0) AS units_sold_90d,
                      CASE WHEN COALESCE(v.units_90d, 0) = 0 THEN NULL
                           ELSE CAST(p.stock_qty / (v.units_90d / 90.0) AS INTEGER) END AS days_of_cover,
                      MAX(p.reorder_level * 2, CAST(COALESCE(v.units_90d, 0) / 90.0 * 45 + 0.999 AS INTEGER))
                          - p.stock_qty AS suggested_reorder_qty
               FROM products p LEFT JOIN velocity v ON v.product_id = p.product_id
               WHERE p.stock_qty <= p.reorder_level AND (:category IS NULL OR p.category = :category)
               ORDER BY days_of_cover IS NULL, days_of_cover""",
            {"category": category},
        )
        return {"category": category or "all", **result.to_dict()}

    # ------------------------------------------------------------------ preset 4
    @mcp.tool(annotations=READ_ONLY, auth=perms.require(READ))
    def customer_profile(
        customer: Annotated[str, Field(description="Customer id (e.g. '42'), full or partial name, or email.")],
    ) -> dict:
        """A 360° view of one customer: profile, lifetime revenue, orders, favourite category and last 5 orders.

        If several customers match a partial name, returns the candidates so you can ask which one.
        """
        needle = customer.strip()
        if "@" in needle and not perms.has(PII):
            raise ToolError("Looking customers up by email requires the bella:pii scope. Search by name or id instead.")
        if needle.isdigit():
            where, params = "customer_id = :v", {"v": int(needle)}
        elif "@" in needle:
            where, params = "lower(email) = lower(:v)", {"v": needle}
        else:
            where, params = "name LIKE :v", {"v": f"%{needle}%"}
        matches = query(f"SELECT customer_id, name, segment, country, city, email AS email, signup_date FROM customers "
                        f"WHERE {where} ORDER BY name LIMIT 10", params)
        if not matches.rows:
            raise ToolError(f"No customer matches {customer!r}. Try part of the name, or browse with top_customers.")
        if len(matches.rows) > 1:
            return {"matches": [{k: r[k] for k in ("customer_id", "name", "segment", "country")} for r in matches.rows],
                    "note": "Several customers match. Ask the user which one, then call again with the customer_id."}

        profile = matches.rows[0]
        cid = {"id": profile["customer_id"]}
        kpis = query("""SELECT ROUND(COALESCE(SUM(revenue), 0), 2) AS lifetime_revenue,
                               COUNT(DISTINCT order_id) AS orders, MIN(order_date) AS first_order,
                               MAX(order_date) AS last_order,
                               ROUND(SUM(revenue) / NULLIF(COUNT(DISTINCT order_id), 0), 2) AS avg_order_value
                        FROM sales WHERE customer_id = :id""", cid).rows[0]
        favourite = query("""SELECT category FROM sales WHERE customer_id = :id
                             GROUP BY category ORDER BY SUM(revenue) DESC LIMIT 1""", cid).rows
        recent = query("""SELECT o.order_id, o.order_date, o.status, o.channel,
                                 ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) AS order_value
                          FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
                          WHERE o.customer_id = :id
                          GROUP BY o.order_id ORDER BY o.order_date DESC LIMIT 5""", cid)
        out = {"profile": profile, "kpis": kpis, "favourite_category": favourite[0]["category"] if favourite else None,
               "recent_orders": recent.rows}
        if matches.redacted_columns:
            out["privacy_note"] = "Email hidden for your role (requires bella:pii)."
        return out

    # ------------------------------------------------------------------ the general query
    @mcp.tool(annotations=READ_ONLY, auth=perms.require(QUERY))
    def ask_bella(
        question: Annotated[str, Field(description="A business question in plain English, OR one read-only SQL "
                                                    "SELECT statement (SQLite dialect, schema in bella://schema).")],
    ) -> dict:
        """Ask Bella anything about Brightline Outdoor's data that the preset tools don't cover.

        Bella turns plain-English questions into SQL using the company's business definitions, runs it
        safely (read-only, row and time limits) and returns the rows plus the SQL she used.
        You may also send a SELECT yourself. Returns at most 200 rows: aggregate in SQL when possible.
        """
        perms.ensure(QUERY)  # also enforced here: stdio skips the auth= check above
        text = question.strip()
        if _SQL_START.match(text):
            sql, explanation, source = text, "SQL provided by the client.", "client-sql"
        else:
            try:
                draft = brain.write_sql(text, schema)
            except BrainUnavailable as exc:
                raise ToolError(str(exc)) from None
            sql, explanation, source = draft.sql, draft.explanation, f"bella-brain ({brain.provider})"
        try:
            result = query(sql)
        except ToolError as exc:
            raise ToolError(f"{exc} [SQL tried: {sql}]") from None
        return {"question": text, "answered_by": source, "sql": sql, "explanation": explanation, **result.to_dict()}

    # ------------------------------------------------------------------ resource + prompt
    @mcp.resource("bella://schema", name="schema", mime_type="text/markdown", auth=perms.require(READ))
    def schema_resource() -> str:
        """Tables, columns and the business glossary (what 'revenue', 'AOV', 'active customer' mean)."""
        return schema

    @mcp.prompt(auth=perms.require(READ))
    def monthly_business_review(month: Annotated[str, Field(description="Month to review, YYYY-MM.")]) -> str:
        """A ready-made monthly business review (MBR) using Bella's tools."""
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            raise ValueError("month must look like 2026-08")
        year, mon = map(int, month.split("-"))
        prev = f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"
        return (
            f"Prepare Brightline Outdoor's Monthly Business Review for {month}, using Bella's tools.\n"
            f"1. sales_summary group_by=month for {prev} and {month} (compare: revenue, orders, AOV, margin %).\n"
            f"2. sales_summary group_by=category and group_by=region for {month} only.\n"
            f"3. top_customers limit=5 for {month}.\n"
            f"4. inventory_alerts (current stock risks).\n"
            "Then write the MBR: a one-line headline, a KPI table vs. the previous month with % change, what drove "
            "the change (category/region), the top 5 customers, stock risks, and 3 concrete recommended actions. "
            "Keep it under 300 words and cite the numbers you used."
        )

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": "bella", "version": __version__,
                             "auth_mode": settings.auth_mode, "brain": brain.provider})

    return mcp


def _date(value: str | None, name: str) -> str | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ToolError(f"{name} must be a date like 2026-01-31 (got {value!r}).") from None
