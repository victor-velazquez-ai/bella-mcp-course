import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from bella_mcp.server import build_server

ALL_TOOLS = {"sales_summary", "top_customers", "inventory_alerts", "customer_profile", "ask_bella"}


@pytest.fixture
def server(make_settings):
    return lambda role="analyst": build_server(make_settings(local_role=role))


async def test_analyst_sees_all_five_tools(server):
    async with Client(server("analyst")) as c:
        assert {t.name for t in await c.list_tools()} == ALL_TOOLS


async def test_viewer_cannot_see_or_call_ask_bella(server):
    async with Client(server("viewer")) as c:
        assert {t.name for t in await c.list_tools()} == ALL_TOOLS - {"ask_bella"}
        with pytest.raises(ToolError):
            await c.call_tool("ask_bella", {"question": "SELECT 1"})


async def test_tools_are_read_only(server):
    async with Client(server()) as c:
        for tool in await c.list_tools():
            assert tool.annotations.readOnlyHint is True


async def test_sales_summary_matches_raw_sql(server):
    async with Client(server()) as c:
        summary = (await c.call_tool("sales_summary", {"group_by": "category"})).data
        raw = (await c.call_tool("ask_bella", {"question": "SELECT ROUND(SUM(revenue), 2) AS r FROM sales"})).data
        assert summary["totals"]["revenue"] == pytest.approx(raw["rows"][0]["r"], abs=1)
        assert len(summary["rows"]) == 6


async def test_bad_date_is_an_actionable_error(server):
    async with Client(server()) as c:
        r = await c.call_tool("sales_summary", {"start_date": "31/01/2026"}, raise_on_error=False)
        assert r.is_error and "like 2026-01-31" in r.content[0].text


async def test_top_customers_limit_is_validated_by_schema(server):
    async with Client(server()) as c:
        with pytest.raises(Exception):
            await c.call_tool("top_customers", {"limit": 500})


async def test_top_customers_masks_email_for_analyst_not_admin(server):
    async with Client(server("analyst")) as c:
        rows = (await c.call_tool("top_customers", {"limit": 3})).data["rows"]
        assert all(r["email"] is None for r in rows)
    async with Client(server("admin")) as c:
        rows = (await c.call_tool("top_customers", {"limit": 3})).data["rows"]
        assert all("@" in r["email"] for r in rows)


async def test_inventory_alerts_are_below_reorder_level(server):
    async with Client(server()) as c:
        rows = (await c.call_tool("inventory_alerts", {})).data["rows"]
        assert rows and all(r["stock_qty"] <= r["reorder_level"] for r in rows)


async def test_customer_profile_ambiguous_then_exact(server):
    async with Client(server()) as c:
        ambiguous = (await c.call_tool("customer_profile", {"customer": "Alpine"})).data
        assert len(ambiguous["matches"]) > 1
        cid = str(ambiguous["matches"][0]["customer_id"])
        profile = (await c.call_tool("customer_profile", {"customer": cid})).data
        assert profile["profile"]["customer_id"] == int(cid) and "lifetime_revenue" in profile["kpis"]


async def test_email_lookup_requires_pii(server):
    async with Client(server("analyst")) as c:
        r = await c.call_tool("customer_profile", {"customer": "someone@example.com"}, raise_on_error=False)
        assert r.is_error and "bella:pii" in r.content[0].text


async def test_ask_bella_demo_brain_and_fallback(server):
    async with Client(server()) as c:
        known = (await c.call_tool("ask_bella", {"question": "revenue by month"})).data
        assert known["answered_by"].startswith("bella-brain") and known["row_count"] == 21
        unknown = await c.call_tool("ask_bella", {"question": "which rep closed the most deals?"}, raise_on_error=False)
        assert unknown.is_error and "SQL" in unknown.content[0].text


async def test_ask_bella_rejects_writes(server):
    async with Client(server()) as c:
        r = await c.call_tool("ask_bella", {"question": "DROP TABLE customers"}, raise_on_error=False)
        assert r.is_error and "read-only" in r.content[0].text


async def test_resource_and_prompt(server):
    async with Client(server("viewer")) as c:
        schema = (await c.read_resource("bella://schema"))[0].text
        assert "Business glossary" in schema and "sales" in schema
        prompt = await c.get_prompt("monthly_business_review", {"month": "2026-08"})
        assert "2026-07" in prompt.messages[0].content.text


async def test_every_call_is_audited(server, make_settings):
    settings = make_settings(local_role="analyst")
    async with Client(build_server(settings)) as c:
        await c.call_tool("inventory_alerts", {})
    entry = json.loads(settings.audit_log_path.read_text().splitlines()[-1])
    assert entry["tool"] == "inventory_alerts" and entry["who"] == "local" and entry["outcome"] == "ok"
