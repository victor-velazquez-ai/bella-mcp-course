"""Run Bella.

    python -m bella_mcp            # stdio: Claude Desktop / Claude Code launch it as a subprocess
    python -m bella_mcp http       # Streamable HTTP on http://localhost:8000/mcp
"""

from __future__ import annotations

import logging
import sys
from urllib.parse import urlparse

from .config import Settings
from .server import build_server


def main() -> None:
    transport = (sys.argv[1] if len(sys.argv) > 1 else "stdio").lower()
    # Logs go to stderr. In stdio mode stdout carries the protocol: one stray print() breaks it.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(message)s")
    settings = Settings()

    if transport == "stdio":
        if settings.auth_mode != "none":
            # MCP auth is an HTTP concern: a stdio server trusts the user who launched it.
            logging.warning("BELLA_AUTH_MODE=%s ignored over stdio (local role: %s)", settings.auth_mode, settings.local_role)
            settings.auth_mode = "none"
        build_server(settings).run(transport="stdio", show_banner=False)
    elif transport == "http":
        extra_hosts = [urlparse(settings.public_url).hostname] if settings.public_url else None
        build_server(settings).run(
            transport="http",
            host=settings.host,
            port=settings.port,
            path="/mcp",
            stateless_http=True,  # no sticky sessions: any replica behind a load balancer can answer
            allowed_hosts=extra_hosts,  # accept the public hostname when running behind a tunnel/proxy
        )
    else:
        raise SystemExit(f"Unknown transport {transport!r}. Use: python -m bella_mcp [stdio|http]")


if __name__ == "__main__":
    main()
