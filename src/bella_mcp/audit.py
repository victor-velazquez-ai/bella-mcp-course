"""Layer 6: every tool call leaves a trace — who, what, how long, and the outcome.

Middleware wraps every request, so tools stay free of logging code. Lines go to a
JSONL file (easy to ship to Splunk/Datadog/CloudWatch) and to stderr.
Never print to stdout in an MCP server: over stdio, stdout IS the protocol channel.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastmcp.server.middleware import Middleware, MiddlewareContext

log = logging.getLogger("bella.audit")


class AuditMiddleware(Middleware):
    def __init__(self, path: Path, who: Callable[[], str]):
        self.path = path
        self.who = who
        path.parent.mkdir(parents=True, exist_ok=True)

    async def on_call_tool(self, context: MiddlewareContext, call_next) -> Any:
        started = time.perf_counter()
        outcome = "ok"
        try:
            result = await call_next(context)
            if getattr(result, "is_error", False):
                outcome = "error"
            return result
        except Exception as exc:
            outcome = f"error: {exc}"[:300]
            raise
        finally:
            self._write({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "who": self.who(),
                "tool": context.message.name,
                "args": _truncate(context.message.arguments or {}),
                "ms": int((time.perf_counter() - started) * 1000),
                "outcome": outcome,
            })

    def _write(self, entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False)
        log.info(line)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _truncate(args: dict, limit: int = 500) -> dict:
    return {k: (v[:limit] + "…" if isinstance(v, str) and len(v) > limit else v) for k, v in args.items()}
