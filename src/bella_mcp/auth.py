"""Authentication (who are you?) and authorization (what may you do?).

Authentication — three modes, one env var (BELLA_AUTH_MODE):

  none    stdio / local dev. No token; the local user gets BELLA_LOCAL_ROLE.
  jwt     The server is an OAuth 2.1 *resource server*: it validates a bearer JWT
          (signature, issuer, audience, expiry) and reads its scopes. In the course
          the "identity provider" is scripts/mint_token.py; in a company you point
          BELLA_JWKS_URI at Entra ID / Okta / Auth0 / Keycloak — same code.
  github  Full OAuth login for claude.ai custom connectors. GitHub has no Dynamic
          Client Registration, so FastMCP's GitHubProvider acts as an OAuth proxy:
          it publishes the discovery metadata, registers Claude, sends the user to
          GitHub, and issues its own tokens. GitHub tokens never reach the client.

Authorization — scopes, mapped from roles:

  viewer   bella:read                        the 4 preset tools + schema
  analyst  bella:read bella:query            + ask_bella (free-form questions/SQL)
  admin    bella:read bella:query bella:pii  + sees personal data (emails)

Each tool declares the scope it needs (`auth=perms.require(...)`). Over HTTP, FastMCP
runs the check on tools/list AND tools/call, so a viewer never even sees ask_bella.
Over stdio FastMCP skips these checks (the spec: a local process trusts the user who
launched it), so sensitive tools ALSO check inside (`perms.ensure(...)`): a lock on
the door and a lock on the safe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, AuthCheck, AuthContext, AuthProvider
from fastmcp.server.dependencies import get_access_token

from .config import Settings

log = logging.getLogger("bella.auth")

READ, QUERY, PII = "bella:read", "bella:query", "bella:pii"
ROLE_SCOPES: dict[str, frozenset[str]] = {
    "viewer": frozenset({READ}),
    "analyst": frozenset({READ, QUERY}),
    "admin": frozenset({READ, QUERY, PII}),
    "none": frozenset(),
}


@dataclass(frozen=True)
class Caller:
    name: str
    scopes: frozenset[str]


def build_auth(settings: Settings) -> AuthProvider | None:
    mode = settings.auth_mode
    if mode == "none":
        return None

    if mode == "jwt":
        from fastmcp.server.auth.providers.jwt import JWTVerifier

        if settings.jwks_uri:  # a real identity provider publishes its keys here
            return JWTVerifier(jwks_uri=settings.jwks_uri, issuer=settings.jwt_issuer, audience=settings.jwt_audience)
        if not settings.jwt_public_key_path.exists():
            raise SystemExit("BELLA_AUTH_MODE=jwt needs keys: run `python scripts/mint_token.py analyst` once, "
                             "or set BELLA_JWKS_URI to your identity provider.")
        return JWTVerifier(
            public_key=settings.jwt_public_key_path.read_text(),
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,  # a token minted for another API is rejected
        )

    if mode == "github":
        from fastmcp.server.auth.providers.github import GitHubProvider

        if not (settings.github_client_id and settings.github_client_secret and settings.public_url):
            raise SystemExit("BELLA_AUTH_MODE=github needs GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET and BELLA_PUBLIC_URL.")
        return GitHubProvider(
            client_id=settings.github_client_id,
            client_secret=settings.github_client_secret,
            base_url=settings.public_url,  # GitHub OAuth App callback: <public_url>/auth/callback
            jwt_signing_key=settings.jwt_signing_key or None,
        )

    raise SystemExit(f"Unknown BELLA_AUTH_MODE={mode!r}. Use none, jwt or github.")


class Permissions:
    """Turns whatever the auth layer verified into Bella's scopes."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def caller(self, token: AccessToken | None = None) -> Caller:
        token = token if token is not None else get_access_token()
        mode = self.settings.auth_mode
        if mode == "none" or token is None:
            if mode != "none":
                return Caller("anonymous", ROLE_SCOPES["none"])
            return Caller("local", ROLE_SCOPES.get(self.settings.local_role, ROLE_SCOPES["viewer"]))
        if mode == "github":
            login = str((token.claims or {}).get("login") or token.subject or "unknown")
            role = self.settings.github_roles.get(login.lower(), self.settings.github_default_role)
            return Caller(f"github:{login}", ROLE_SCOPES.get(role, ROLE_SCOPES["none"]))
        # jwt: the identity provider decided the scopes; we only read them.
        return Caller(str(token.subject or token.client_id), frozenset(token.scopes or ()))

    def require(self, scope: str) -> AuthCheck:
        def check(ctx: AuthContext) -> bool:
            return scope in self.caller(ctx.token).scopes

        check.__name__ = f"require_{scope.replace(':', '_')}"
        return check

    def has(self, scope: str) -> bool:
        return scope in self.caller().scopes

    def ensure(self, scope: str) -> None:
        """Enforce inside the tool: works on every transport, including stdio."""
        if not self.has(scope):
            raise ToolError(f"Your role doesn't include the {scope} scope required for this.")
