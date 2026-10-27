"""Lesson 4 — a tour of Bella, as three different people.

Calls every tool, the resource and the prompt the way Claude would — and shows how
the SAME server looks different to a viewer, an analyst and an admin.
Also the plan-B demo: if Claude or the network fails during a live session, run this.

    python lessons/04_bella_tour.py
"""

import asyncio
import json
import sys

from fastmcp import Client

from bella_mcp.config import Settings
from bella_mcp.server import build_server

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")


def brief(data, rows: int = 3) -> str:
    """Trim long row lists so the output fits on a slide."""
    if isinstance(data, dict):
        data = {k: (v[:rows] + ["…"] if isinstance(v, list) and len(v) > rows else v) for k, v in data.items()}
    return json.dumps(data, ensure_ascii=False, default=str)[:700]


async def main() -> None:
    for role in ("viewer", "analyst", "admin"):
        async with Client(build_server(Settings(local_role=role))) as bella:
            names = [t.name for t in await bella.list_tools()]
            print(f"\n=== as {role.upper():<7} → sees {len(names)} tools: {', '.join(names)}")
            if role == "viewer":
                r = await bella.call_tool("ask_bella", {"question": "revenue by region"}, raise_on_error=False)
                print("  ask_bella →", r.content[0].text if r.is_error else "allowed?!")
            r = await bella.call_tool("top_customers", {"limit": 2, "segment": "Enterprise"})
            print("  top_customers →", brief(r.data, 2))

    async with Client(build_server(Settings(local_role="analyst"))) as bella:
        print("\n=== the other tools, as an analyst")
        calls = [
            ("sales_summary", {"group_by": "region", "start_date": "2026-01-01"}),
            ("inventory_alerts", {}),
            ("customer_profile", {"customer": "Canyon Tours"}),  # ambiguous → candidates
            ("customer_profile", {"customer": "317"}),           # by id → full profile
            ("ask_bella", {"question": "What is our revenue by category?"}),
            ("ask_bella", {"question": "SELECT channel, COUNT(*) AS orders FROM orders GROUP BY channel"}),
        ]
        for tool, args in calls:
            r = await bella.call_tool(tool, args, raise_on_error=False)
            print(f"\n  {tool}({args}) →\n    {r.content[0].text[:300] if r.is_error else brief(r.data)}")

        schema = await bella.read_resource("bella://schema")
        print("\n  resource bella://schema →", schema[0].text.splitlines()[0], "…")
        prompt = await bella.get_prompt("monthly_business_review", {"month": "2026-08"})
        print("  prompt monthly_business_review →", prompt.messages[0].content.text.splitlines()[0])


if __name__ == "__main__":
    asyncio.run(main())
