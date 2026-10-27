"""Lesson 2 — what Claude actually sees.

Part A launches lesson 1 as a subprocess over stdio — exactly what Claude Desktop
and Claude Code do — then lists its tools and calls one.
Part B connects to Bella (in-memory) and prints the full definition of one tool:
the description and JSON Schema Claude reads to decide WHEN and HOW to call it.

    python lessons/02_what_claude_sees.py
"""

import asyncio
import json
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

from bella_mcp.server import build_server

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

HELLO = Path(__file__).with_name("01_hello_mcp.py")


def show(title: str, payload) -> None:
    print(f"\n── {title} " + "─" * max(0, 60 - len(title)))
    print(payload if isinstance(payload, str) else json.dumps(payload, indent=2, ensure_ascii=False))


async def main() -> None:
    # Part A — a real stdio connection to lesson 1
    async with Client(PythonStdioTransport(HELLO)) as client:
        tools = await client.list_tools()
        show("A. tools/list from lesson 1 (over stdio)", [t.model_dump(exclude_none=True, by_alias=True) for t in tools])
        result = await client.call_tool("greet", {"name": "Ada", "excited": True})
        show("A. tools/call greet → result", result.data)

    # Part B — Bella's surface
    async with Client(build_server()) as client:
        show("B. Bella's instructions (sent to the client)", client.instructions or "")
        tools = await client.list_tools()
        show("B. Bella's tools", [t.name for t in tools])
        summary = next(t for t in tools if t.name == "sales_summary")
        show("B. The full definition of sales_summary", summary.model_dump(exclude_none=True, by_alias=True))
        print("\nEverything above came from Python type hints + docstrings. Good descriptions = good tool choices.")


if __name__ == "__main__":
    asyncio.run(main())
