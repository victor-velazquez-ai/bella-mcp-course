import os
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest

os.environ["MOCK"] = "1"  # tests never call a paid model

from bella_mcp.config import Settings  # noqa: E402
from bella_mcp.seed import build_database  # noqa: E402


@pytest.fixture(scope="session")
def db_path(tmp_path_factory) -> Path:
    return build_database(tmp_path_factory.mktemp("data") / "bella.db")


@pytest.fixture
def make_settings(db_path, tmp_path):
    def make(**overrides) -> Settings:
        return Settings(db_path=db_path, audit_log_path=tmp_path / "audit.jsonl", rate_limit_per_second=100, **overrides)

    return make


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_in_thread(mcp, port: int) -> None:
    """Run a real HTTP server (uvicorn) in the background and wait until /health answers."""
    threading.Thread(
        target=lambda: mcp.run(transport="http", host="127.0.0.1", port=port, show_banner=False, stateless_http=True),
        daemon=True,
    ).start()
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("server did not start")
