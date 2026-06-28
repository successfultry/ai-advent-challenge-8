# Week 04 — MCP, Tools & Tool Orchestration

## Structure

```
week_04/
├── main.py                 # entrypoint: REPL mode or --agent mode
├── mcp_client.py           # MCP client + interactive tool calling loop
├── agent.py                # LLM agent that can call MCP tools and use outputs
├── orchestrator.py         # Day 20: multi-server orchestrator (not an MCP server)
├── mcp_server.py           # Day 16: local filesystem MCP server
├── mcp_server_api.py       # Day 17: MCP server wrapping external HTTP APIs
├── market_watch/           # Day 18: scheduler + SQLite + market-summary agent
├── tech_radar/             # Day 20: github/pypi/radar/reports MCP servers
├── targets.py              # target + orchestration profile registry
├── tests/test_mcp_server_api.py  # pytest checks for Day 17 API server
├── tests/test_market_watch.py    # pytest checks for Day 18 market watch
└── tests/test_tech_radar_*.py  # pytest checks for Day 20 tech_radar flow
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
| `places` | `python -m week_04.mcp_server_places` (Foursquare pipeline) | stdio | ours | Foursquare key |
| `github` | `python -m week_04.tech_radar.mcp_server_github` | stdio | ours | network |
| `pypi` | `python -m week_04.tech_radar.mcp_server_pypi` | stdio | ours | network |
| `radar` | `python -m week_04.tech_radar.mcp_server_radar` | stdio | ours | Python only |
| `reports` | `python -m week_04.tech_radar.mcp_server_reports` | stdio | ours | local fs |

Orchestration profiles (agent mode only):

- `tech_radar` -> `github + pypi + radar + reports`

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

`tests/test_mcp_server_api.py` covers:
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
deterministically and the LLM receives aggregate JSON, returns strict JSON content,
and code renders the final Telegram layout (emoji + HTML).

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
| `MARKET_WATCH_INTERVAL_S` | `10` | server-side collector interval |
| `MARKET_WATCH_LIMIT` | `20` | binary markets kept per collection (each → Yes/No, so 20 = 40 snapshots) |
| `MARKET_WATCH_DB` | `week_04/market_watch.db` | SQLite runtime DB path |
| `TELEGRAM_BOT_TOKEN` | unset | optional Telegram bot token for watcher push |
| `TELEGRAM_CHAT_ID` | unset | optional Telegram chat or channel id |

Recommended production overrides:

```bash
MARKET_WATCH_INTERVAL_S=3600
MARKET_WATCH_LIMIT=20
```

### Run (bash)

```bash
# offline-safe demo: no tokens, survives DNS/network errors
uv run python -m week_04.market_watch.watcher --cycles 1 --interval 1 --no-llm

# live 24/7 agent loop with EN+RU LLM phrasing
uv run python -m week_04.market_watch.watcher --interval 60 --window 1h --lang both

# production profile: report twice per day, movers over last 12h
uv run python -m week_04.market_watch.watcher --provider "DeepSeek V3" --interval 43200 --window 12h --lang both
```

Telegram push is optional. If `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set,
the watcher sends each generated summary to Telegram after printing it locally.
The LLM remains mandatory on the default path; Telegram formatting is deterministic code.

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
uv run pytest week_04/tests/test_market_watch.py -q
```

`tests/test_market_watch.py` covers pure aggregation, Manifold response parsing, and SQLite
storage using temporary databases. It does not call the network, LLM, or stdio MCP server.

### Inspect the database

```bash
uv run python -c "import sqlite3; db=sqlite3.connect('week_04/market_watch.db'); db.row_factory=sqlite3.Row; [print(dict(r)) for r in db.execute('SELECT * FROM snapshots ORDER BY volume DESC LIMIT 20')]"
```

Clear runtime data before a fresh live demo (also removes WAL files):

```powershell
Remove-Item week_04/market_watch.db*
```

### Troubleshooting

Manifold uses a public JSON API at `https://api.manifold.markets` and does not require auth.
If it is temporarily unreachable, the collector logs failures and keeps running.

### Docker (local)

```bash
docker build -t market-watch .
docker run --rm --env-file .env market-watch
```

The image runs the watcher with:

```bash
uv run python -m week_04.market_watch.watcher --provider "DeepSeek V3" --interval 60 --window 12h --lang both
```

Override command if needed:

```bash
docker run --rm --env-file .env market-watch uv run python -m week_04.market_watch.watcher --cycles 1 --interval 1 --no-llm
```

### Railway (worker deploy)

1. Create a new Railway project from this GitHub repo.
2. Add environment variables from `.env`:
   - `OPENAI_API_KEY` (or your chosen provider key)
   - `MANIFOLD_API_URL` (optional override)
   - `MARKET_WATCH_INTERVAL_S`, `MARKET_WATCH_LIMIT`, `MARKET_WATCH_DB`
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (optional)
3. Set start command:

```bash
uv run python -m week_04.market_watch.watcher --provider "DeepSeek V3" --interval 43200 --window 12h --lang both
```

4. Deploy as a worker service (no public HTTP port required).

---

## Day 19 — MCP tool composition (Foursquare Places pipeline)

### Goal

Build a 3-tool MCP pipeline where the LLM agent automatically chains tool calls from one
free-form user prompt. There is no hardcoded call sequence in the client.

### Architecture

```
User prompt
    │
    ▼
LLM agent (agent.py)  ←──── discovers tools from MCP server ────►  mcp_server_places.py
    │                                                                  ├── search_places
    │  tool_call #1: search_places(near=..., query=...)                ├── build_report
    │  tool_call #2: build_report(data_json=..., top_n=..., ...)       └── save_to_file
    │  tool_call #3: save_to_file(content=..., filename=...)
    ▼
Final answer + file saved to week_04/places_outputs/
```

- **MCP server** exposes 3 deterministic tools (no LLM inside the server).
- **LLM** receives tool schemas, reads the user prompt, and decides the call order itself.
- **Data**: real Foursquare Places API (global venue database, requires `FOURSQUARE_API_KEY`).

### Day 19 tools (`--target places`)

| Tool | Purpose |
|------|---------|
| `search_places(near, query, limit, sort, open_now, min_price, max_price)` | Fetch real venues from Foursquare Places API |
| `build_report(data_json, top_n, max_distance_m)` | Filter by distance, sort nearest first, build markdown |
| `save_to_file(content, filename)` | Write report to `week_04/places_outputs/<filename>` |

`sort` accepts only `RELEVANCE` and `DISTANCE`. Foursquare also accepts `RATING` and
`POPULARITY`, but the rating/popularity values are Premium fields and are not returned on
the free Pro tier, so they are intentionally not exposed in this demo.

Price filters:

Foursquare supports `min_price`/`max_price` as search filters from `1` to `4`:

- `1` = cheap / budget (`$`)
- `2` = moderate (`$$`)
- `3` = expensive (`$$$`)
- `4` = very expensive / upscale (`$$$$`)

Examples:

- "недорогие places" -> `max_price=2`
- "самые дешевые places" -> `max_price=1`
- "средний ценник" -> `min_price=2`, `max_price=3`
- "дорогие / премиальные places" -> `min_price=3`, `max_price=4`

These filters limit search results by price tier. The actual `price` value is a Premium
response field, so it is not returned or shown in the report.

### Data semantics

- `distance` is straight-line metres from the geocoded center of `near` to the place.
  It is not measured from the current user location.
- Returned Pro fields: `name`, `location`, `categories`, `distance`, `tel`, `website`.
- Premium fields are not requested: `rating`, `popularity`, `price`, `hours`, `photos`,
  `tips`, `tastes`, `description`, `stats`.
- The prompt can be free-form. For any places search/report request, the agent should chain
  `search_places` -> `build_report` -> `save_to_file`.
- The report is saved even when the user does not explicitly ask to save it. If no filename
  is provided, the agent chooses a sensible one like `places_report_lisbon_coffee.md`.
- Prompts without a place/city cannot run `search_places` because the API needs `near`.
- Multi-city comparisons can exceed the agent's `_MAX_STEPS = 5` guard.

### Pro vs Premium fields (billing)

This demo requests only Foursquare Pro fields:

- `name`
- `location`
- `categories`
- `distance`
- `tel`
- `website`

Premium fields are not requested:

- `rating`
- `popularity`
- `price`
- `hours`
- `photos`
- `tips`
- `tastes`
- `description`
- `stats`

Notes:

- Each request still counts toward the Pro quota.
- Pro calls are free until the free quota limit, then billed by Pro pricing.
- Requesting Premium fields without credits returns a Foursquare API billing error.

### Env

```bash
FOURSQUARE_API_KEY=<your service API key>
```

Get a free key at [location.foursquare.com/developer](https://location.foursquare.com/developer) →
create a project → Settings → Generate Service API Key.
Free tier: 10,000 requests/month (Pro fields only; `rating`/`popularity` are Premium).

### Run

```bash
# Manual REPL (inspect tools, call manually)
uv run python -m week_04.main --target places

# Agent auto-chain with --ask (Russian prompt, explicit filename)
uv run python -m week_04.main --target places --agent --provider "GPT-4o mini" \
  --ask "Найди italian restaurants в Санкт-Петербурге, топ-5 ближайших к центру города в пределах 2 км, сохрани отчёт в spb_italian.md"

# Agent auto-chain without --ask: enter the Russian question at Ask>
uv run python -m week_04.main --target places --agent --provider "GPT-4o mini"

# No explicit filename: agent should still save the report with a sensible filename
uv run python -m week_04.main --target places --agent --provider "GPT-4o mini" \
  --ask "Найди coffee shops в Лиссабоне, топ-7 ближайших к центру города"
```

### Russian prompts to test

Use these either with `--ask "..."` or paste one into `Ask>` when running without `--ask`.
Use English place categories inside Russian prompts (`italian restaurants`, `sushi
restaurants`, `coffee shops`) because Foursquare matches them more reliably than broad
Russian phrases like "японская кухня".

```text
Найди italian restaurants в Санкт-Петербурге, топ-5 ближайших к центру города в пределах 2 км, сохрани отчёт в spb_italian.md
```

```text
Найди sushi restaurants в Токио, топ-3 ближайших к центру города, сохрани отчёт в tokyo_sushi.md
```

```text
Найди coffee shops в Лиссабоне, топ-7 ближайших к центру города
```

```text
Найди bakeries в Праге, топ-5 ближайших к центру города в пределах 1500 метров, сохрани отчёт в prague_bakeries.md
```

```text
Найди ramen restaurants в Osaka, топ-5 ближайших к центру города, сохрани отчёт в osaka_ramen.md
```

```text
Найди pizza restaurants в Rome, топ-6 ближайших к центру города, сохрани отчёт в rome_pizza.md
```

```text
Найди Mexican restaurants в Madrid, топ-5 ближайших к центру города в пределах 3 км
```

```text
Найди bookstores в London, топ-5 ближайших к центру города, сохрани отчёт в london_bookstores.md
```

```text
Найди parks в Berlin, топ-5 ближайших к центру города, сохрани отчёт в berlin_parks.md
```

```text
Найди museums в Paris, топ-5 ближайших к центру города, сохрани отчёт в paris_museums.md
```

### Expected output

```
tools available to LLM: ['search_places', 'build_report', 'save_to_file']

User: Find 10 italian restaurants near Saint Petersburg, ...

  -> call search_places({'near': 'Saint Petersburg', 'query': 'italian restaurant', 'limit': 10})
  <- {"near": "Saint Petersburg", "query": "italian restaurant", "count": 10, ...}

  -> call build_report({'data_json': '...', 'top_n': 5, 'max_distance_m': 2000})
  <- {"shown": 5, "total": 10, "report_markdown": "## Places: italian restaurant near ..."}

  -> call save_to_file({'content': '## Places: ...', 'filename': 'spb_italian.md'})
  <- {"ok": true, "path": "week_04/places_outputs/spb_italian.md", "bytes": 847}

Agent: Done! I found 10 Italian restaurants near Saint Petersburg, selected the 5 closest
within 2 km, and saved the report to week_04/places_outputs/spb_italian.md.
```

### Tests

```bash
uv run pytest week_04/tests/test_places_server.py -q
```

Covers: search_places validation, build_report sorting + distance filter (including
`distance_m=None` edge behavior), save_to_file path-traversal guard. No live network calls.

---

## Day 20 — MCP orchestration across multiple servers (Tech Radar)

### Goal

Build one agent flow that orchestrates tools across multiple MCP servers:

- choose the right tool by intent
- route every call to the right server session
- execute a long flow with dependencies between calls

### Architecture

```
User prompt
    │
    ▼
Orchestrator agent (agent.py + orchestrator.py)
    │
    ├── github server (search_repos, get_repo, get_readme_excerpt)
    ├── pypi server   (get_package, recent_releases)
    ├── radar server  (extract_requirements, normalize_candidates, build_comparison)
    └── reports server (save_report, list_reports, load_report)
```

`orchestrator.py` is not an MCP server. It opens multiple MCP sessions concurrently,
collects tools with qualified names (`github__...`, `pypi__...`, `radar__...`,
`reports__...`), and routes each tool call by prefix.

No tool is pre-called by Python code: the LLM agent selects and orders every tool call itself, including the first `radar__extract_requirements` step.

Division of labor: MCP servers are sensors + deterministic scoring; the LLM agent chooses
all tools, orchestrates the flow, and authors the final markdown report. No MCP tool calls
an LLM.

### Run

```bash
uv run python -m week_04.main --target tech_radar --agent --provider "GPT-4o mini" \
  --ask "Find Python libraries for data validation in a backend service. Discover candidates first, evaluate the top 3 using GitHub and PyPI evidence, apply requirement-aware scoring for maintained, typed, production-ready libraries, save the report as py_validation_radar_2026, then list saved reports."
```

```bash

uv run python -m week_04.main --target tech_radar --agent --provider "DeepSeek V3" --ask "Помоги выбрать Python-библиотеку для валидации данных в продакшн-бэкенде. Найди несколько подходящих вариантов, сравни три лучших по доступным данным, оформи итоговый markdown-отчёт, сохрани его и покажи список сохранённых отчётов. Числовые оценки бери из результата сравнения, не пересчитывай и не придумывай их сам."
```

### Expected log excerpt (agent-driven)

```text
tools available to LLM: ['github__search_repos', 'github__get_repo', 'github__get_readme_excerpt', 'pypi__get_package', 'pypi__recent_releases', 'radar__extract_requirements', 'radar__normalize_candidates', 'radar__build_comparison', 'reports__save_report', 'reports__list_reports', 'reports__load_report']

User: Find Python libraries for data validation in a backend service...

  -> call radar__extract_requirements({'user_prompt': 'Find Python libraries...'})
  <- {"use_case": "data validation", ...}

  -> call github__search_repos({'query': 'python data validation typed production-ready library', 'limit': 10})
  <- {"count": 10, ...}

  -> call radar__normalize_candidates({...})
  -> call github__get_repo({...})
  -> call github__get_readme_excerpt({...})
  -> call pypi__get_package({...})
  -> call pypi__recent_releases({...})
  -> call radar__build_comparison({...})
  -> LLM authors markdown report from build_comparison output
  -> call reports__save_report({'content': '# Tech Radar Report\n...', 'slug': 'py_validation_radar_2026'})
  -> call reports__list_reports({})
```

### Expected long flow

1. `radar__extract_requirements`
2. `github__search_repos`
3. `radar__normalize_candidates`
4. `github__get_repo` (for each candidate)
5. `github__get_readme_excerpt` (for each candidate)
6. `pypi__get_package` (for each candidate)
7. `pypi__recent_releases` (for each candidate)
8. `radar__build_comparison` (with enriched candidate evidence)
9. LLM writes markdown report from `build_comparison` output
10. `reports__save_report`
11. `reports__list_reports`

Wrong order examples:

- `radar__build_comparison` before evidence collection
- `reports__save_report` before the LLM has authored markdown from comparison output
- calling `pypi` tools through `github__...` prefix

### Verification checklist

- The run log shows qualified tool names from at least 4 server prefixes.
- Tool order follows the dependency chain above.
- Report is saved under `week_04/tech_radar_outputs/`.
- `list_reports` returns the saved file.
- Saved report includes GitHub + PyPI evidence (stars, versions, latest release date) and
  per-rank recommendations.

### Tests

```bash
uv run pytest week_04/tests/test_tech_radar_orchestrator.py week_04/tests/test_tech_radar_radar.py week_04/tests/test_tech_radar_reports.py -q
```

Covers: qualified routing, unknown route guard, strict enriched candidate normalization,
deterministic scoring + package confidence penalty behavior, partial evidence tolerance,
reports path safety, orchestration profile membership.

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
| Foursquare premium credits error | remove Premium fields (`rating`, `popularity`, `price`, `hours`, `photos`, `tips`, etc.) from `fields`, or add billing credits |

---

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 16 | MCP connection + interactive tool calls over stdio/http targets (`own`, `time`, `remote`) | `-m week_04.main`, `--target own\|time\|remote` | `mcp_server.py`, `mcp_client.py`, `targets.py`, `main.py` | done | _link_ |
| 17 | Own API-wrapping MCP server (`api`) + LLM agent that calls tools and uses results | `-m week_04.main --target api`, `--agent --ask "..."`, `pytest week_04 -q` | `mcp_server_api.py`, `agent.py`, `targets.py`, `main.py`, `tests/test_mcp_server_api.py` | done | _link_ |
| 18 | Market Watch MCP server with scheduled collection, SQLite aggregation, and 24/7 watcher agent | `-m week_04.market_watch.watcher --cycles 1 --no-llm`, `pytest week_04/tests/test_market_watch.py -q` | `market_watch/`, `targets.py`, `tests/test_market_watch.py` | done | _link_ |
| 19 | MCP tool composition: 3-tool Foursquare Places pipeline, LLM auto-chains | `-m week_04.main --target places --agent --ask "..."`, `pytest week_04/tests/test_places_server.py -q` | `mcp_server_places.py`, `targets.py`, `tests/test_places_server.py` | done | _link_ |
| 20 | MCP orchestration across 4 servers (Tech Radar), long routed flow with qualified tool prefixes | `-m week_04.main --target tech_radar --agent --ask "..."`, `pytest week_04/tests/test_tech_radar_orchestrator.py week_04/tests/test_tech_radar_radar.py week_04/tests/test_tech_radar_reports.py -q` | `tech_radar/`, `orchestrator.py`, `agent.py`, `targets.py`, `main.py`, `tests/test_tech_radar_*.py` | done | _link_ |

All days share one codebase; this table maps each day to commands and modules.








