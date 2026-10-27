# Make it yours — turn Bella into a portfolio project

Recruiters and clients can't evaluate "I know MCP". They can evaluate a repo where a real AI client queries real data safely, with tests and a 60-second video. Here's the path from this course repo to **your** project.

## 1. Pick your data (30 min)

Swap Brightline Outdoor for something you care about or a domain you want to work in:

| Domain | Data source | Presets that make sense |
|---|---|---|
| E-commerce | Olist (Kaggle), your Shopify export | sales_summary, top_customers, churn_risk |
| Finance | your bank CSVs, SEC filings | monthly_spend, category_trends, anomalies |
| HR / People | synthetic HRIS | headcount_by_team, attrition, open_roles |
| Sports | football-data.org, Kaggle | team_form, top_scorers, head_to_head |
| Real estate | public listings | price_per_m2, days_on_market, comparables |

Keep it SQLite to start (load CSVs with `sqlite3` or `pandas.to_sql`). Moving to Postgres later is a `db.py` change.

## 2. Rename and rewire (1 hour)

1. Fork this repo (or "Use this template"), rename it (e.g. `nova-finance-mcp`).
2. Rename the package `bella_mcp` → `your_mcp` (folder + imports + `pyproject.toml`).
3. Rewrite `seed.py` for your data, and the `sales` view → **your semantic layer** (the one agreed definition of your key metrics).
4. Replace the 4 presets with the 4 questions your users ask most. Keep `ask_bella` (rename it) for everything else.
5. Update `PII_COLUMNS` in `db.py` for your personal-data columns.
6. Rewrite the server `instructions`, tool docstrings and the glossary in `schema_markdown()` — **these are prompts**: they decide whether Claude picks the right tool.

## 3. Keep the enterprise bits (they ARE the differentiator)

- [ ] Read-only connection + authorizer + limits (`db.py`) — and `lessons/03_attack_the_guard.py` adapted to your data
- [ ] Roles/scopes, tools hidden by role (`auth.py`)
- [ ] Audit log + rate limiting (`audit.py`)
- [ ] Tests green in CI: copy `docs/ci.yml` to `.github/workflows/ci.yml` (runs `verify.py` on every push)
- [ ] `python verify.py` green

## 4. Ship it (1 hour)

- Deploy the Dockerfile (Render / Railway / Fly.io free tiers work), `BELLA_AUTH_MODE=github`, your login as admin.
- Add it to Claude as a custom connector and record a **60-90 second demo**: a business question → Claude picks a tool → answer; a viewer can't see the query tool; an injection attempt gets blocked.

## 5. Present it

**README** (top to bottom): one-line pitch · GIF of the demo · "Connect in 2 minutes" · tools table · security model (the 6 layers) · architecture diagram · tests badge.

**LinkedIn / CV line**, e.g.:
> Built an enterprise MCP server that lets Claude answer business questions over a sales database — OAuth 2.1 (GitHub), role-based tool access, column-level PII masking, SQL guard with 6 defense layers, audit logging; 50+ tests incl. auth over real HTTP.

**Interview talking points**: why MCP instead of a custom API · resource server vs authorization server · why the LLM's SQL is untrusted input · stdio vs HTTP trust model · what you'd add next (Postgres + row-level security, OpenTelemetry traces, MCP Apps UI, a registry entry).

## 6. Go further

- Publish to the **MCP Registry** so others can discover it.
- Add an **MCP App** (interactive chart UI) to `sales_summary`.
- Add a write tool behind a human confirmation (elicitation) — and a `destructiveHint`.
- Swap GitHub for your company's IdP (`docs/auth.md`).
