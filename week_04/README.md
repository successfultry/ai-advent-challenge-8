# Week 04 — MCP, Tools & Tool Orchestration

## Structure

```
week_04/
├── main.py                 # entrypoint: REPL mode or --agent mode
├── mcp_client.py           # MCP client + interactive tool calling loop
├── agent.py                # LLM agent that can call MCP tools and use outputs
├── mcp_server.py           # Day 16: local filesystem MCP server
├── mcp_server_api.py       # Day 17: MCP server wrapping external HTTP APIs
├── market_watch/           # Day 18: scheduler + SQLite + market-summary agent
├── targets.py              # target registry (own, time, remote, api, market_watch)
├── test_mcp_server_api.py  # pytest checks for Day 17 API server
└── test_market_watch.py    # pytest checks for Day 18 market watch
```

No `__init__.py` in `week_04/` (PEP 420 namespace package), same run style as week_02/week_03:
`uv run python -m week_04.main`.

## Targets

| Target | Server | Transport | Whose | Requires |
|--------|--------|-----------|-------|----------|
| `own` (default) | `python -m week_04.mcp_server` (week04-fs, 3 file tools) | stdio | ours | Python only |
| `time` | `uvx mcp-server-time` | stdio | external (Anthropic) | uvx |
| `remote` | `https://mcp.deepwiki.com/mcp` (DeepWiki, 3 tools) | Streamable HTTP | external (Devin) | network |
| `api` | `python -m week_04.mcp_server_api` (4 tools over JSONPlaceholder + Open-Meteo) | stdio | ours | network |
| `market_watch` | `python -m week_04.market_watch.server` (Manifold watch tools) | stdio | ours | network |

## Base setup

```bash
uv add "mcp[cli]"
# for --agent mode, put at least one provider key in .env (e.g. OPENAI_API_KEY)
```

---

## Day 16 — MCP Connection + tools/list + manual call_tool

### Goal

- Establish MCP connection
- Run `initialize`
- Run `tools/list`
- Manually call tools from the app

### Run (bash)

```bash
# local filesystem MCP server
uv run python -m week_04.main --target own

# external stdio MCP server
uv run python -m week_04.main --target time

# external HTTP MCP server
uv run python -m week_04.main --target remote
```

### What to verify

- `initialize -> ok (...)`
- `tools/list -> N tools`
- at least one successful tool call per target

### Example outputs

`own -> list_files` with `{}`:
```
D __pycache__
F README.md
F main.py
F mcp_client.py
F mcp_server.py
F targets.py
```

`time -> get_current_time` with `{"timezone": "UTC"}`:
```
{
  "timezone": "UTC",
  "datetime": "2026-06-23T11:22:35+00:00",
  "day_of_week": "Tuesday",
  "is_dst": false
}
```

`remote -> read_wiki_structure` with `{"repoName": "facebook/react"}`:
```
Available pages for facebook/react:
- 1 React Repository Overview
  - 1.1 Repository Structure and Packages
  ...
- 8 Glossary
```

---

## Day 17 — Own MCP server around external APIs + agent uses results

### Goal

Build our own MCP server (`mcp_server_api.py`) around external APIs and prove that an
LLM agent calls tools and uses outputs in its final answer.

### Day 17 tools (`--target api`)

- `list_posts(limit=10)` — JSONPlaceholder
- `get_post(post_id)` — JSONPlaceholder
- `create_post(title, body, userId=1)` — JSONPlaceholder (fake create, returns `id=101`)
- `get_current_weather(lat, lon)` — Open-Meteo

### Run and test manually first (bash)

```bash
# REPL mode (manual MCP tool calls)
uv run python -m week_04.main --target api
```

In the REPL, call at least:
- `get_post` with `{"post_id": 1}`
- `create_post` with `{"title": "hello", "body": "world", "userId": 1}`
- `get_current_weather` with `{"lat": 55.75, "lon": 37.62}`

Expected sample outputs:

`get_post`:
```
{
  "id": 1,
  "title": "sunt aut facere repellat provident occaecati excepturi optio reprehenderit",
  "body": "quia et suscipit\nsuscipit recusandae consequuntur expedita et cum...",
  "userId": 1
}
```

`create_post`:
```
{"title": "hello", "body": "world", "userId": 1, "id": 101}
```

`get_current_weather`:
```
{"time": "2026-06-24T07:30", "temperature": 19.6, "windspeed": 9.2, "weathercode": 2}
```

### Agent proof (bash)

```bash
uv run python -m week_04.main --target api --agent \
  --provider "GPT-4o mini" \
  --ask "Weather in Moscow (55.75, 37.62)? Then title of post #1."
```

Expected behavior:
- logs show tool calls (`-> call get_current_weather`, `-> call get_post`)
- final agent answer uses both tool results

### Bonus auto-tests (pytest)

```bash
uv run pytest week_04 -q
```

Expected line:
```
12 passed
```

`test_mcp_server_api.py` covers:
- 4 tools are registered
- required params schema checks
- live smoke checks for `list_posts`, `get_post`, `create_post`

---

## Day 18 — Market Watch scheduler + 24/7 agent

### Goal

Build an MCP tool with scheduled/periodic execution, SQLite storage, aggregation, and a
24/7 agent that periodically emits a market summary.

### Architecture

Day 18 uses a FastMCP service + adapter pattern:

- `server.py` is the FastMCP adapter. It exposes thin tools and owns the server-side
  background collector loop.
- `store.py` is the SQLite storage layer.
- `manifold.py` is the public Manifold Markets API adapter.
- `aggregate.py` is pure aggregation/statistics.
- `watcher.py` is the agent-side 24/7 loop. It keeps one MCP session open, periodically
  calls tools, and optionally asks an LLM to phrase the summary.

The Day 18 24/7 agent is `watcher.py`. `agent.py` is the Day 17 one-shot tool-calling
agent used by `week_04.main --agent --ask`.

The "both schedulers" decision is intentional: the server collects data on its own
interval, and the watcher runs the agent loop on its own interval.

### Day 18 tools (`--target market_watch`)

| Tool | Purpose |
|------|---------|
| `collect_now()` | Fetch active Manifold quotes and store snapshots immediately |
| `latest_markets()` | Return the latest stored snapshot per `(market_id, outcome)` |
| `build_summary(window="all", top_n=10)` | Aggregate latest/history, persist summary, return JSON |
| `latest_summary()` | Return the latest persisted summary |

`collect_now` writes (HTTP to Manifold + INSERT), `latest_markets`/`latest_summary`
only read from SQLite. The LLM never calls tools: the watcher loop calls them
deterministically and the LLM only phrases the resulting aggregate JSON.

### Notes

- Only `BINARY` markets are tracked; `MULTIPLE_CHOICE` are skipped. `limit` counts
  binary markets, each stored as two rows (`Yes`/`No`), so `limit=10` = 20 snapshots.
- Markets come from `/v0/markets` (newest 100), then sorted by volume locally —
  "top by volume among recent", not globally hottest markets.
- `volume` is Manifold mana (M$); `volume24Hours` is preferred when present.
- `top_movers` is empty until a series has at least two snapshots in the window.
- Two independent timers: server collector (`MARKET_WATCH_INTERVAL_S`) vs watcher
  agent loop (`--interval`).

### Env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `MANIFOLD_API_URL` | `https://api.manifold.markets` | Manifold API base URL override |
| `MARKET_WATCH_INTERVAL_S` | `60` | server-side collector interval |
| `MARKET_WATCH_LIMIT` | `10` | binary markets kept per collection (each → Yes/No, so 10 = 20 snapshots) |
| `MARKET_WATCH_DB` | `week_04/market_watch.db` | SQLite runtime DB path |

### Run (bash)

```bash
# offline-safe demo: no tokens, survives DNS/network errors
uv run python -m week_04.market_watch.watcher --cycles 1 --interval 1 --no-llm

# live 24/7 agent loop with EN+RU LLM phrasing
uv run python -m week_04.market_watch.watcher --interval 60 --window 1h --lang both
```

Useful watcher flags:

- `--interval 60` — seconds between agent cycles
- `--window 1h` — summary window (`all`, `1h`, `24h`, `7d`)
- `--cycles 1` — finite run for demos/tests
- `--no-llm` — deterministic summary only, no tokens
- `--lang en|ru|both` — LLM summary language; `both` returns English and Russian sections

Expected offline-safe behavior:

- watcher connects to the `market-watch` MCP server
- `collect_now` fetches live Manifold binary markets when the network is available
- `build_summary` still returns a deterministic summary
- process exits cleanly after one cycle when `--cycles 1` is used

### Tests

```bash
uv run pytest week_04/test_market_watch.py -q
```

`test_market_watch.py` covers pure aggregation, Manifold response parsing, and SQLite
storage using temporary databases. It does not call the network, LLM, or stdio MCP server.

### Inspect the database

```bash
uv run python -c "import sqlite3; db=sqlite3.connect('week_04/market_watch.db'); db.row_factory=sqlite3.Row; [print(dict(r)) for r in db.execute('SELECT * FROM snapshots ORDER BY id DESC LIMIT 10')]"
```

Clear runtime data before a fresh live demo (also removes WAL files):

```powershell
Remove-Item week_04/market_watch.db*
```

### Troubleshooting

Manifold uses a public JSON API at `https://api.manifold.markets` and does not require auth.
If it is temporarily unreachable, the collector logs failures and keeps running.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `uvx not found` | install/update uv; `uvx` ships with uv |
| timeout on first `time` run | first `uvx` run downloads package, retry (client timeout is 60s) |
| invalid JSON args in REPL | input must be JSON object, e.g. `{}` or `{"post_id": 1}` |
| `remote` unreachable | public endpoint may be down; retry later or use `own`/`api` |
| `--agent` fails with missing key | set provider key in `.env` (`OPENAI_API_KEY`, etc.) |
| `market_watch` returns 0 markets | check Manifold/network availability, or use the offline-safe watcher demo |

---

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 16 | MCP connection + interactive tool calls over stdio/http targets (`own`, `time`, `remote`) | `-m week_04.main`, `--target own\|time\|remote` | `mcp_server.py`, `mcp_client.py`, `targets.py`, `main.py` | done | _link_ |
| 17 | Own API-wrapping MCP server (`api`) + LLM agent that calls tools and uses results | `-m week_04.main --target api`, `--agent --ask "..."`, `pytest week_04 -q` | `mcp_server_api.py`, `agent.py`, `targets.py`, `main.py`, `test_mcp_server_api.py` | done | _link_ |
| 18 | Market Watch MCP server with scheduled collection, SQLite aggregation, and 24/7 watcher agent | `-m week_04.market_watch.watcher --cycles 1 --no-llm`, `pytest week_04/test_market_watch.py -q` | `market_watch/`, `targets.py`, `test_market_watch.py` | done | _link_ |

All days share one codebase; this table maps each day to commands and modules.
