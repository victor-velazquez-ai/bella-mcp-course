# Bella — an enterprise MCP server for Claude

**Course repo for _"Build an Enterprise MCP Server: Connect Claude to Your Company's Data"_** by Victor Velázquez.

Bella is the AI data analyst of *Brightline Outdoor* (a fictional outdoor-gear retailer). She lives behind an **MCP server**, so you can ask Claude — Desktop, Code or claude.ai — *"who were our top Enterprise customers this year?"* and get an answer from the company database, safely.

```
You ─▶ Claude ─▶ MCP ─▶ Bella ─▶ guard ─▶ SQLite (read-only)
                        │  5 tools · 1 resource · 1 prompt
                        └─ auth (none / JWT / GitHub OAuth) · scopes · PII masking · audit · rate limits
```

- ✅ Runs with **zero API keys** (demo mode) — add `ANTHROPIC_API_KEY` for Bella's full brain
- ✅ stdio **and** Streamable HTTP · MCP spec **2026-07-28** via FastMCP 4
- ✅ OAuth 2.1 resource server · roles → scopes → tools · column-level PII masking
- ✅ 52 tests, including auth over real HTTP and the stdio transport

---

## Run it in 3 minutes

```bash
git clone https://github.com/victor-velazquez-ai/bella-mcp-course.git
cd bella-mcp-course
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
python data/seed.py               # builds data/bella.db (also auto-built on first start)
python verify.py                  # everything green? you're ready
```

Then connect it to Claude (details and 4 options in [docs/connect-to-claude.md](docs/connect-to-claude.md)):

```bash
claude mcp add bella -- python -m bella_mcp        # Claude Code, from the activated venv
```

Ask: *"Using Bella, how did revenue evolve by month this year, and which products are about to run out?"*

## Bella's surface

| # | Tool | What | Scope |
|---|---|---|---|
| 1 | `sales_summary` | revenue, orders, units, AOV, margin % by month / category / region / channel | `bella:read` |
| 2 | `top_customers` | top customers by revenue for a period, optional segment | `bella:read` |
| 3 | `inventory_alerts` | products at/below reorder level, days of cover, suggested reorder | `bella:read` |
| 4 | `customer_profile` | 360° view of one customer (by id, name or email) | `bella:read` |
| 5 | `ask_bella` | **general query**: plain English (Bella writes the SQL) or a read-only SELECT | `bella:query` |

Plus the resource **`bella://schema`** (schema + business glossary) and the prompt **`monthly_business_review(month)`**.
All tools are annotated `readOnlyHint: true` and return structured output.

## Security: six layers between a prompt and your data

```
1 scopes      ask_bella needs bella:query — without it the tool is invisible        auth.py
2 shape       exactly one SELECT / WITH statement                                    db.py
3 read-only   SQLite opened with mode=ro                                             db.py
4 authorizer  reads only; emails read as NULL without bella:pii (aliases can't help) db.py
5 limits      200 rows · 2 s timeout · 1 MB values                                   db.py
6 audit       every call → logs/audit.jsonl (who, tool, args, ms, outcome) + rate limit  audit.py
```

The SQL Bella's own brain writes is treated as **untrusted input** and goes through the same guard. Try to break it: `python lessons/03_attack_the_guard.py`.

## Auth modes

| `BELLA_AUTH_MODE` | For | How |
|---|---|---|
| `none` (default) | stdio, local dev | local user gets `BELLA_LOCAL_ROLE` (default `analyst`) |
| `jwt` | tokens from any IdP | signature + issuer + audience + expiry + scopes. Local IdP: `python scripts/mint_token.py analyst` |
| `github` | claude.ai custom connector | full OAuth 2.1 login via GitHub (OAuth proxy, PKCE, discovery metadata) |

Roles: **viewer** (`bella:read`) · **analyst** (+ `bella:query`) · **admin** (+ `bella:pii`). Details and Entra ID / Okta / Auth0 / Keycloak setup: [docs/auth.md](docs/auth.md).

## Repo map (course Part 2 → files)

| Step | Files |
|---|---|
| P1 setup | `pyproject.toml`, `data/seed.py`, `verify.py` |
| P2 MCP in 10 lines · what Claude sees | `lessons/01_hello_mcp.py`, `lessons/02_what_claude_sees.py` |
| P3 data layer & SQL guard | `src/bella_mcp/db.py`, `lessons/03_attack_the_guard.py` |
| P4 the 4 presets | `src/bella_mcp/server.py` |
| P5 `ask_bella` + Bella's brain | `src/bella_mcp/server.py`, `src/bella_mcp/brain.py` |
| P6 enterprise layer | `src/bella_mcp/auth.py`, `src/bella_mcp/audit.py`, `scripts/mint_token.py` |
| P7 connect to Claude | `src/bella_mcp/__main__.py`, `.mcp.json`, `docs/connect-to-claude.md`, `Dockerfile` |
| Plan-B demo | `lessons/04_bella_tour.py` |

```
src/bella_mcp/
  config.py   settings from env (.env)          db.py      the guard (layers 2-5) + schema
  seed.py     builds the demo database          brain.py   English → SQL (Claude / OpenAI / demo)
  auth.py     auth modes, roles, scopes         audit.py   audit middleware (layer 6)
  server.py   build_server(): tools, resource, prompt, /health
  __main__.py python -m bella_mcp [stdio|http]
```

## Commands

```bash
python -m bella_mcp                        # stdio (Claude Desktop / Code launch this)
python -m bella_mcp http                   # http://localhost:8000/mcp  · health: /health
BELLA_AUTH_MODE=jwt python -m bella_mcp http
python scripts/mint_token.py viewer --decode
python -m pytest -q
docker build -t bella . && docker run -p 8000:8000 bella
```

## Make it yours

Swap the data, keep the architecture, ship it, put it in your portfolio: [docs/make-it-yours.md](docs/make-it-yours.md).

---

Built with [FastMCP](https://gofastmcp.com) 4 on the [Model Context Protocol](https://modelcontextprotocol.io). Data is synthetic. MIT licensed. Never commit your `.env`.
