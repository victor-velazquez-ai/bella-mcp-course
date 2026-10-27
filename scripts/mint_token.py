"""A tiny local "identity provider" for the course: issues signed JWTs per role.

In a company this is Entra ID / Okta / Auth0 / Keycloak. Here it's 40 lines, so you
can SEE what an access token is: a signed JSON document saying who you are (sub),
who issued it (iss), who it's for (aud), until when (exp), and what you may do (scope).

    python scripts/mint_token.py analyst            # prints a token (8h)
    python scripts/mint_token.py viewer --who bob
    python scripts/mint_token.py admin --decode     # also show what's inside

First run creates keys/private.pem (keep secret) + keys/public.pem (the server only
needs this one: it can VERIFY tokens but never MINT them — that separation is the point).
"""

from __future__ import annotations

import argparse
import base64
import json
import sys

from pydantic import SecretStr

from bella_mcp.auth import ROLE_SCOPES
from bella_mcp.config import ROOT, Settings
from fastmcp.server.auth.providers.jwt import RSAKeyPair

KEYS = ROOT / "keys"


def load_or_create_keys() -> RSAKeyPair:
    private, public = KEYS / "private.pem", KEYS / "public.pem"
    if private.exists() and public.exists():
        return RSAKeyPair(private_key=SecretStr(private.read_text()), public_key=public.read_text())
    KEYS.mkdir(exist_ok=True)
    pair = RSAKeyPair.generate()
    private.write_text(pair.private_key.get_secret_value())
    public.write_text(pair.public_key)
    print(f"Created a new key pair in {KEYS}", file=sys.stderr)
    return pair


def mint(role: str, who: str | None = None, hours: float = 8) -> str:
    settings = Settings()
    return load_or_create_keys().create_token(
        subject=who or f"{role}@brightline.example",
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        scopes=sorted(ROLE_SCOPES[role]),
        expires_in_seconds=int(hours * 3600),
        additional_claims={"role": role},
    )


def decode(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mint a Bella access token")
    parser.add_argument("role", choices=["viewer", "analyst", "admin"])
    parser.add_argument("--who", help="the token subject (default: <role>@brightline.example)")
    parser.add_argument("--hours", type=float, default=8)
    parser.add_argument("--decode", action="store_true", help="print the token's claims too")
    args = parser.parse_args()
    token = mint(args.role, args.who, args.hours)
    if args.decode:
        print(json.dumps(decode(token), indent=2), file=sys.stderr)
    print(token)
