"""Settings, read once from the environment (and .env).

12-factor style: every knob is an environment variable with a safe default, so the
same code runs on a laptop over stdio and in a container behind OAuth. Paths are
resolved from the repo root, not the current directory, because Claude Desktop
launches the server from wherever it likes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def _roles(value: str) -> dict[str, str]:
    """'alice:admin, bob:analyst' -> {'alice': 'admin', 'bob': 'analyst'}"""
    pairs = (item.split(":", 1) for item in value.split(",") if ":" in item)
    return {login.strip().lower(): role.strip() for login, role in pairs}


@dataclass
class Settings:
    # Data
    db_path: Path = field(default_factory=lambda: _path(os.getenv("BELLA_DB_PATH", "data/bella.db")))
    max_rows: int = int(os.getenv("BELLA_MAX_ROWS", "200"))
    query_timeout_ms: int = int(os.getenv("BELLA_QUERY_TIMEOUT_MS", "2000"))

    # Server
    host: str = os.getenv("BELLA_HOST", "127.0.0.1")
    port: int = int(os.getenv("BELLA_PORT") or os.getenv("PORT") or "8000")
    public_url: str = os.getenv("BELLA_PUBLIC_URL", "").rstrip("/")

    # Auth: none | jwt | github
    auth_mode: str = os.getenv("BELLA_AUTH_MODE", "none").strip().lower()
    local_role: str = os.getenv("BELLA_LOCAL_ROLE", "analyst")
    jwt_issuer: str = os.getenv("BELLA_JWT_ISSUER", "https://auth.brightline.local")
    jwt_audience: str = os.getenv("BELLA_JWT_AUDIENCE", "bella-mcp")
    jwks_uri: str = os.getenv("BELLA_JWKS_URI", "")
    jwt_public_key_path: Path = field(default_factory=lambda: ROOT / "keys" / "public.pem")
    github_client_id: str = os.getenv("GITHUB_CLIENT_ID", "")
    github_client_secret: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    github_roles: dict[str, str] = field(default_factory=lambda: _roles(os.getenv("BELLA_GITHUB_ROLES", "")))
    github_default_role: str = os.getenv("BELLA_GITHUB_DEFAULT_ROLE", "viewer")
    jwt_signing_key: str = os.getenv("BELLA_JWT_SIGNING_KEY", "")

    # Operations
    audit_log_path: Path = field(default_factory=lambda: _path(os.getenv("BELLA_AUDIT_LOG", "logs/audit.jsonl")))
    rate_limit_per_second: float = float(os.getenv("BELLA_RATE_LIMIT_PER_SECOND", "5"))

    @property
    def base_url(self) -> str:
        return self.public_url or f"http://localhost:{self.port}"
