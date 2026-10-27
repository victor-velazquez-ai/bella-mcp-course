"""Lesson 1 — an MCP server in 10 lines.

    python lessons/01_hello_mcp.py          # speaks MCP over stdio (it will just wait: that's correct)
    python lessons/01_hello_mcp.py http     # or over HTTP at http://localhost:8000/mcp

Connect it to Claude Code (use the absolute path), then ask Claude: "greet Ada":
    claude mcp add hello -- python /full/path/to/lessons/01_hello_mcp.py

What FastMCP does for you: the type hints become the tool's JSON Schema, the
docstring becomes its description, and the return value becomes the result.
Lesson 2 shows exactly what Claude receives.
"""

import sys

from fastmcp import FastMCP

mcp = FastMCP("Hello")


@mcp.tool
def greet(name: str, excited: bool = False) -> str:
    """Greet someone by name. Use it whenever the user asks to say hello to a person."""
    return f"Hello, {name}{'!!!' if excited else '.'} (sent by your first MCP server)"


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "http":
        mcp.run(transport="http", port=8000)
    else:
        mcp.run(show_banner=False)  # stdio: the client launches us and talks over stdin/stdout
