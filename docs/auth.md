# Auth in Bella — and how to plug in your company's identity provider

## The vocabulary

- **Authentication** — *who are you?* Proven by a token.
- **Authorization** — *what may you do?* Decided by scopes/roles in that token.
- In MCP, a remote server is an **OAuth 2.1 resource server**: it never sees passwords; it validates tokens issued by an **authorization server** (Entra ID, Okta, Auth0, Keycloak, Google, GitHub…).
- Auth is an **HTTP** concern. A stdio server is a local process launched by the user — it takes credentials from its environment (spec: stdio servers *SHOULD NOT* follow the OAuth flow).

## Bella's three modes (`BELLA_AUTH_MODE`)

| Mode | What validates the caller | When |
|---|---|---|
| `none` | nobody — local process, role from `BELLA_LOCAL_ROLE` | stdio, development |
| `jwt` | `JWTVerifier`: signature, `iss`, `aud`, `exp`, scopes | services/CLIs that already hold a token; any OIDC IdP |
| `github` | `GitHubProvider` (an OAuth **proxy**) | interactive login from claude.ai custom connectors |

## Roles → scopes → tools

| Role | Scopes | Sees |
|---|---|---|
| viewer | `bella:read` | 4 presets + `bella://schema` + the MBR prompt |
| analyst | `bella:read bella:query` | + `ask_bella` |
| admin | `bella:read bella:query bella:pii` | + personal data (emails) |

- Each tool declares its scope: `@mcp.tool(auth=perms.require("bella:query"))`. Over HTTP FastMCP applies it to `tools/list` **and** `tools/call` — unauthorized tools are invisible.
- Over stdio FastMCP skips those checks (local = trusted), so `ask_bella` also calls `perms.ensure("bella:query")` inside. Lock on the door *and* on the safe.
- PII is enforced **in the database layer** (SQLite authorizer): `customers.email` reads as `NULL` without `bella:pii`, whatever SQL is sent.

## Using a real identity provider (jwt mode)

Point Bella at your IdP's JWKS and tell it which issuer/audience to accept:

```bash
BELLA_AUTH_MODE=jwt
BELLA_JWKS_URI=https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys      # Entra ID
BELLA_JWT_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
BELLA_JWT_AUDIENCE=api://bella-mcp
```

| IdP | JWKS URI | Where scopes/roles live |
|---|---|---|
| Entra ID | `https://login.microsoftonline.com/<tenant>/discovery/v2.0/keys` | `scp` (delegated) / `roles` (app roles) |
| Okta | `https://<org>.okta.com/oauth2/<server-id>/v1/keys` | `scp` |
| Auth0 | `https://<tenant>.auth0.com/.well-known/jwks.json` | `scope` / `permissions` |
| Keycloak | `https://<host>/realms/<realm>/protocol/openid-connect/certs` | `scope` / `realm_access.roles` |

Define `bella:read`, `bella:query`, `bella:pii` as scopes (or app roles) in the IdP and assign them to groups. If your IdP puts roles in a custom claim, read them in `Permissions.caller()` (`auth.py`) — FastMCP's `require_roles(..., extract=...)` exists for exactly this.

For **interactive login from claude.ai** with a corporate IdP, swap `GitHubProvider` for the matching FastMCP provider (`AzureProvider`, `GoogleProvider`, `Auth0Provider`/`Auth0MCPProvider`, `AWSCognitoProvider`, `KeycloakAuthProvider`, `WorkOSProvider`/`AuthKitProvider`…) or, if your IdP supports Client ID Metadata Documents / DCR, a `RemoteAuthProvider` that simply points clients at it.

## Rules that never change

1. Validate **audience**: a token minted for another API must be rejected (`tests/test_auth.py` proves it).
2. **No token passthrough**: never forward the client's token to downstream APIs. Use your own credentials or a token exchange.
3. Tokens in the `Authorization` header only — never in URLs, never in logs.
4. Least privilege: the default role for unknown users should be the smallest one (`viewer`) or `none`.
5. Stable signing keys in production (`BELLA_JWT_SIGNING_KEY`), secrets from the environment / a vault — never in git.
