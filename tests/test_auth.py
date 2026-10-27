"""Auth over REAL HTTP: a uvicorn server in a thread, real bearer tokens, real 401s."""

import json
import sys
import urllib.error
import urllib.request

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.server.auth.providers.jwt import RSAKeyPair

from bella_mcp.auth import ROLE_SCOPES
from bella_mcp.server import build_server

from .conftest import free_port, serve_in_thread

ISSUER, AUDIENCE = "https://auth.brightline.local", "bella-mcp"


@pytest.fixture(scope="module")
def keys():
    return RSAKeyPair.generate()


@pytest.fixture(scope="module")
def jwt_server(keys, db_path, tmp_path_factory):
    from bella_mcp.config import Settings

    tmp = tmp_path_factory.mktemp("jwt")
    (tmp / "public.pem").write_text(keys.public_key)
    settings = Settings(db_path=db_path, auth_mode="jwt", jwt_public_key_path=tmp / "public.pem",
                        audit_log_path=tmp / "audit.jsonl", rate_limit_per_second=100)
    port = free_port()
    serve_in_thread(build_server(settings), port)
    return f"http://127.0.0.1:{port}", settings


def token(keys, role="analyst", **overrides) -> str:
    claims = dict(subject=f"{role}@brightline.example", issuer=ISSUER, audience=AUDIENCE,
                  scopes=sorted(ROLE_SCOPES[role]))
    claims.update(overrides)
    return keys.create_token(**claims)


def raw_post(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)


def test_no_token_gets_401_with_bearer_challenge(jwt_server):
    base, _ = jwt_server
    status, headers = raw_post(f"{base}/mcp")
    assert status == 401 and headers.get("www-authenticate", "").startswith("Bearer")


def test_health_is_public(jwt_server):
    base, _ = jwt_server
    body = json.loads(urllib.request.urlopen(f"{base}/health").read())
    assert body["status"] == "ok" and body["auth_mode"] == "jwt"


@pytest.mark.parametrize("role,expected", [("viewer", 4), ("analyst", 5), ("admin", 5)])
async def test_each_role_sees_its_tools(jwt_server, keys, role, expected):
    base, _ = jwt_server
    async with Client(f"{base}/mcp", auth=token(keys, role)) as c:
        assert len(await c.list_tools()) == expected


async def test_admin_sees_emails_analyst_does_not(jwt_server, keys):
    base, _ = jwt_server
    q = {"question": "SELECT email FROM customers LIMIT 1"}
    async with Client(f"{base}/mcp", auth=token(keys, "analyst")) as c:
        assert (await c.call_tool("ask_bella", q)).data["rows"][0]["email"] is None
    async with Client(f"{base}/mcp", auth=token(keys, "admin")) as c:
        assert "@" in (await c.call_tool("ask_bella", q)).data["rows"][0]["email"]


@pytest.mark.parametrize("bad", [
    {"audience": "some-other-api"},          # token minted for a different service
    {"issuer": "https://evil.example"},      # wrong issuer
    {"expires_in_seconds": -60},             # expired
])
async def test_invalid_tokens_are_rejected(jwt_server, keys, bad):
    base, _ = jwt_server
    with pytest.raises(Exception):
        async with Client(f"{base}/mcp", auth=token(keys, **bad)) as c:
            await c.list_tools()


async def test_token_signed_by_another_key_is_rejected(jwt_server):
    base, _ = jwt_server
    forged = RSAKeyPair.generate().create_token(subject="mallory", issuer=ISSUER, audience=AUDIENCE,
                                                scopes=sorted(ROLE_SCOPES["admin"]))
    with pytest.raises(Exception):
        async with Client(f"{base}/mcp", auth=forged) as c:
            await c.list_tools()


async def test_audit_log_records_the_caller(jwt_server, keys):
    base, settings = jwt_server
    async with Client(f"{base}/mcp", auth=token(keys, "viewer", subject="bob")) as c:
        await c.call_tool("inventory_alerts", {})
    entries = [json.loads(line) for line in settings.audit_log_path.read_text().splitlines()]
    assert any(e["who"] == "bob" and e["tool"] == "inventory_alerts" for e in entries)


def test_github_mode_publishes_oauth_discovery(db_path, tmp_path):
    """claude.ai discovers how to log in from these two documents (RFC 9728 + RFC 8414)."""
    from bella_mcp.config import Settings

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    settings = Settings(db_path=db_path, auth_mode="github", github_client_id="test-id",
                        github_client_secret="test-secret", public_url=base, audit_log_path=tmp_path / "a.jsonl")
    serve_in_thread(build_server(settings), port)
    prm = json.loads(urllib.request.urlopen(f"{base}/.well-known/oauth-protected-resource/mcp").read())
    assert prm["resource"].rstrip("/") == f"{base}/mcp" and prm["authorization_servers"]
    meta = json.loads(urllib.request.urlopen(f"{base}/.well-known/oauth-authorization-server").read())
    assert {"authorization_endpoint", "token_endpoint"} <= meta.keys()
    assert "S256" in meta.get("code_challenge_methods_supported", [])
    status, headers = raw_post(f"{base}/mcp")
    assert status == 401 and "resource_metadata" in headers.get("www-authenticate", "")


def stdio(db_path, role: str) -> StdioTransport:
    """Exactly what Claude Desktop does: launch `python -m bella_mcp` and talk over stdin/stdout."""
    return StdioTransport(sys.executable, ["-m", "bella_mcp"],
                          env={"MOCK": "1", "BELLA_DB_PATH": str(db_path), "BELLA_LOCAL_ROLE": role})


async def test_stdio_transport_end_to_end(db_path):
    async with Client(stdio(db_path, "analyst")) as c:
        assert len(await c.list_tools()) == 5
        assert (await c.call_tool("sales_summary", {"group_by": "channel"})).data["row_count"] == 3
        rows = (await c.call_tool("ask_bella", {"question": "SELECT email FROM customers LIMIT 1"})).data["rows"]
        assert rows[0]["email"] is None


async def test_stdio_still_enforces_scopes_inside_tools(db_path):
    # Over stdio FastMCP skips per-tool auth checks (local = trusted), so the tool checks itself.
    async with Client(stdio(db_path, "viewer")) as c:
        r = await c.call_tool("ask_bella", {"question": "SELECT 1"}, raise_on_error=False)
        assert r.is_error and "bella:query" in r.content[0].text
