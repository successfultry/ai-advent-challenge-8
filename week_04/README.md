# Week 04 — MCP, Tools & Tool Orchestration

## Structure

```
week_04/
├── main.py                 # entrypoint: REPL mode or --agent mode
├── mcp_client.py           # MCP client + interactive tool calling loop
├── agent.py                # LLM agent that can call MCP tools and use outputs
├── mcp_server.py           # Day 16: local filesystem MCP server
├── mcp_server_api.py       # Day 17: MCP server wrapping external HTTP APIs
├── targets.py              # target registry (own, time, remote, api)
└── test_mcp_server_api.py  # pytest checks for Day 17 API server
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
6 passed
```

`test_mcp_server_api.py` covers:
- 4 tools are registered
- required params schema checks
- live smoke checks for `list_posts`, `get_post`, `create_post`

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `uvx not found` | install/update uv; `uvx` ships with uv |
| timeout on first `time` run | first `uvx` run downloads package, retry (client timeout is 60s) |
| invalid JSON args in REPL | input must be JSON object, e.g. `{}` or `{"post_id": 1}` |
| `remote` unreachable | public endpoint may be down; retry later or use `own`/`api` |
| `--agent` fails with missing key | set provider key in `.env` (`OPENAI_API_KEY`, etc.) |

---

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 16 | MCP connection + interactive tool calls over stdio/http targets (`own`, `time`, `remote`) | `-m week_04.main`, `--target own\|time\|remote` | `mcp_server.py`, `mcp_client.py`, `targets.py`, `main.py` | done | _link_ |
| 17 | Own API-wrapping MCP server (`api`) + LLM agent that calls tools and uses results | `-m week_04.main --target api`, `--agent --ask "..."`, `pytest week_04 -q` | `mcp_server_api.py`, `agent.py`, `targets.py`, `main.py`, `test_mcp_server_api.py` | done | _link_ |

All days share one codebase; this table maps each day to commands and modules.
