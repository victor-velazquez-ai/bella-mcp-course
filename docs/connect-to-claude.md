# Connect Bella to Claude — 4 ways

| Where | Transport | Auth | Needs a public URL? | Best for |
|---|---|---|---|---|
| Claude Code | stdio | none (local user is trusted) | no | developing, the live course demo |
| Claude Code | HTTP | bearer JWT | no | testing roles & auth locally |
| Claude Desktop | stdio | none | no | non-developers on their own laptop |
| claude.ai / Desktop **custom connector** | HTTP | OAuth (GitHub) | **yes** (HTTPS) | sharing with a team, the "wow" demo |

Before anything: `pip install -e ".[dev]"` inside the repo's virtual environment, then `python verify.py`.

---

## 1. Claude Code over stdio (2 minutes)

From the repo folder, **with the virtual environment activated**:

```bash
claude mcp add bella -- python -m bella_mcp
```

Or do nothing: the repo ships a `.mcp.json`, so opening the folder in Claude Code offers to enable `bella` (project scope).
Check with `/mcp` inside Claude Code, then ask: *"Using Bella, what were our top 5 Enterprise customers this year?"*

**Bella's brain** (turns English into SQL inside `ask_bella`) needs no API key: if Claude Code is installed and logged in, she borrows **your Claude subscription** by running `claude -p` with every tool switched off. Check with `curl http://localhost:8000/health` (HTTP mode) — `"brain": "claude-code"`. If `claude` isn't on Bella's PATH (common with Claude Desktop), set `BELLA_CLAUDE_BIN` in `.env` to its full path. An `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` takes priority; with none of these, `ask_bella` runs in demo mode and Claude simply writes the SQL itself — it still works.

> Subscription mode is for **your own machine**. A deployed server that other people use (the custom connector in §4) should use an API key.

The local role is `analyst` (no personal data). Try `BELLA_LOCAL_ROLE=admin` in `.env` to see emails.

## 2. Claude Code over HTTP with a token

```bash
# terminal 1
BELLA_AUTH_MODE=jwt python -m bella_mcp http          # → http://localhost:8000/mcp

# terminal 2
TOKEN=$(python scripts/mint_token.py viewer)
claude mcp add --transport http bella-viewer http://localhost:8000/mcp --header "Authorization: Bearer $TOKEN"
```

PowerShell: `$env:BELLA_AUTH_MODE="jwt"; python -m bella_mcp http` and `$TOKEN = python scripts/mint_token.py viewer`.

Now `/mcp` → `bella-viewer` shows **4 tools**: `ask_bella` is invisible to a viewer. Add a second server with an `analyst` token and compare. `logs/audit.jsonl` shows who called what.

## 3. Claude Desktop (local, stdio)

Settings → Developer → **Edit Config** opens `claude_desktop_config.json`. Add:

```json
{
  "mcpServers": {
    "bella": {
      "command": "C:\\path\\to\\bella-mcp-course\\.venv\\Scripts\\python.exe",
      "args": ["-m", "bella_mcp"]
    }
  }
}
```

macOS/Linux: `"command": "/path/to/bella-mcp-course/.venv/bin/python"`. Use the **full path to the venv's Python** — Claude Desktop doesn't activate your venv. Restart Claude Desktop; Bella's tools appear under the tools (🔨) menu. The `.env` in the repo is read automatically, whatever folder Desktop starts from.

## 4. claude.ai custom connector (remote, OAuth)

Claude connects to custom connectors **from Anthropic's cloud**, so Bella must be reachable at a public **HTTPS** URL.

1. **Get a public URL** — either deploy (see the Dockerfile; Render/Railway/Fly give you `https://<app>.onrender.com`), or tunnel your laptop: `ngrok http 8000` (a free static ngrok domain keeps the URL stable between runs).
2. **Create a GitHub OAuth App** — github.com → Settings → Developer settings → OAuth Apps → New:
   - Homepage URL: `https://<your-host>`
   - Authorization callback URL: `https://<your-host>/auth/callback`
3. **Configure `.env`** (or the host's environment variables):
   ```
   BELLA_AUTH_MODE=github
   BELLA_PUBLIC_URL=https://<your-host>
   GITHUB_CLIENT_ID=...
   GITHUB_CLIENT_SECRET=...
   BELLA_GITHUB_ROLES=your-github-login:admin
   BELLA_GITHUB_DEFAULT_ROLE=viewer
   BELLA_JWT_SIGNING_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
   ```
4. **Run** `python -m bella_mcp http` and check `https://<your-host>/health`.
5. **In Claude**: Settings → Connectors → **Add custom connector** → URL `https://<your-host>/mcp` → Connect → log in with GitHub → approve the consent screen.

What happens behind "Connect" (the theory, live): Claude calls `/mcp` without a token → **401** with `WWW-Authenticate: Bearer resource_metadata=…` → reads `/.well-known/oauth-protected-resource/mcp` → finds the authorization server → reads `/.well-known/oauth-authorization-server` → registers itself → sends you to GitHub with PKCE → gets a token issued by Bella (never GitHub's token) → calls the tools.

> ⚠️ Never expose Bella publicly with `BELLA_AUTH_MODE=none`. Anyone with the URL could read the data.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Claude Desktop shows the server as failed | Use the full venv Python path; check `%APPDATA%\Claude\logs\mcp*.log` (macOS: `~/Library/Logs/Claude/`) |
| "Unknown tool" / a tool is missing | Your role doesn't have the scope — that's the auth working. Check the token's role. |
| `421 Misdirected Request` behind a tunnel | Set `BELLA_PUBLIC_URL` to the public URL so its hostname is allowed |
| OAuth redirect error from GitHub | The OAuth App callback must be exactly `<BELLA_PUBLIC_URL>/auth/callback` |
| Everyone is logged out after a restart | Set a stable `BELLA_JWT_SIGNING_KEY` |
| `ask_bella` says it's in demo mode | Bella didn't find Claude Code: install it and log in once, or set `BELLA_CLAUDE_BIN` (or add `ANTHROPIC_API_KEY`) in `.env`, then restart Bella — or just let Claude send SQL, which always works |
| `ask_bella`: "brain (Claude Code) failed: Not logged in" | Run `claude` once and `/login` with your Claude account |
