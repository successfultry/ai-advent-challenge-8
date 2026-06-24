# Week 04 — MCP, Tools & Tool Orchestration

## Structure

```
week_04/
├── main.py                 # thin entrypoint: --target REPL or --agent LLM loop
├── mcp_client.py           # ClientSession flow over stdio/http + interactive call_tool loop
├── agent.py                # LLM agent: lets the model call MCP tools and use the results
├── mcp_server.py           # Day 16 FastMCP server: 3 filesystem tools (stdio)
├── mcp_server_api.py       # Day 17 FastMCP server: 4 tools wrapping public HTTP APIs
├── targets.py              # target registry (own, time, remote, api)
└── test_mcp_server_api.py  # pytest: tool registration + live API smoke tests
```

No `__init__.py` in `week_04/` (PEP 420 namespace package), same run style as week_02/week_03:
`uv run python -m week_04.main`.

## Day 16 Goal

Connect to MCP, run `initialize`, run `tools/list`, and visibly show returned tools. Adds an
interactive `call_tool` loop so tools can be invoked from one CLI.

## Day 17 Goal

Implement our **own** MCP server wrapping real external APIs (`mcp_server_api.py`), then have an
**LLM agent** call those tools and use the results in its answer (`agent.py`). Covers tool
registration, typed input params, result return, and agent-driven tool use.

## Targets

All targets use the same `ClientSession`; the difference is transport + whose server it is:

| Target | Server | Transport | Whose | Requires |
|--------|--------|-----------|-------|----------|
| `own` (default) | `python -m week_04.mcp_server` (week04-fs, 3 file tools) | stdio | ours | Python only |
| `time` | `uvx mcp-server-time` | stdio | external (Anthropic) | uvx (ships with uv) |
| `remote` | `https://mcp.deepwiki.com/mcp` (DeepWiki, 3 tools) | Streamable HTTP | external (Devin) | network |
| `api` | `python -m week_04.mcp_server_api` (4 tools over JSONPlaceholder + Open-Meteo) | stdio | ours | network |

## Run

```bash
# Our own MCP server (stdio)
uv run python -m week_04.main --target own

# External MCP server via uvx (stdio, no Node)
uv run python -m week_04.main --target time

# External remote MCP over HTTP (DeepWiki)
uv run python -m week_04.main --target remote

# Day 17: our API-wrapping server (interactive REPL)
uv run python -m week_04.main --target api

# Day 17: LLM agent that calls our tools and uses the results
uv run python -m week_04.main --target api --agent --ask "Weather in Moscow (55.75, 37.62)? Then title of post #1."
```

First-time setup:

```bash
uv add "mcp[cli]"
# LLM agent needs a provider key in .env (e.g. OPENAI_API_KEY); see shared/config.py
```

## Interactive flow

1. Client prints target and protocol trace:
   - `initialize -> ok (...)`
   - `tools/list -> N tools`
2. Client prints indexed tools (`[i] name: description`)
3. Pick a tool number (or `q`)
4. Review tool `inputSchema`
5. Enter args as JSON (`{}` by default)
6. Client calls `session.call_tool(...)` and prints response blocks

## Example calls

### own -> list_files
Args: `{}` (or `{"path": "."}`)
```
D __pycache__
F README.md
F main.py
F mcp_client.py
F mcp_server.py
F targets.py
```

### own -> read_file
Args: `{"path": "README.md"}`  (note: `{}` fails because `path` is required)

### time -> get_current_time
Args: `{"timezone": "UTC"}`
```
{
  "timezone": "UTC",
  "datetime": "2026-06-23T11:22:35+00:00",
  "day_of_week": "Tuesday",
  "is_dst": false
}
```

### remote -> read_wiki_structure
Args: `{"repoName": "facebook/react"}` (fast; `ask_question` works too but is slow + LLM-generated)
```
Available pages for facebook/react:

- 1 React Repository Overview
  - 1.1 Repository Structure and Packages
  - 1.2 Feature Flags System
- 2 Core Reconciler Architecture
  - 2.1 Fiber Work Loop and Scheduling
  ...
- 8 Glossary
```

### api -> get_post (JSONPlaceholder)
Args: `{"post_id": 1}`
```
{
  "id": 1,
  "title": "sunt aut facere repellat provident occaecati excepturi optio reprehenderit",
  "body": "quia et suscipit\nsuscipit recusandae consequuntur expedita et cum...",
  "userId": 1
}
```

### api -> create_post (JSONPlaceholder)
Args: `{"title": "hello", "body": "world", "userId": 1}` (fake create, always returns `id: 101`)
```
{"title": "hello", "body": "world", "userId": 1, "id": 101}
```

### api -> get_current_weather (Open-Meteo)
Args: `{"lat": 55.75, "lon": 37.62}`
```
{"time": "2026-06-24T07:30", "temperature": 19.6, "windspeed": 9.2, "weathercode": 2}
```

## Agent (Day 17 "use the result")

`agent.py` exposes the `api` server's tools to an LLM (OpenAI-compatible, via `shared/`). The
model decides which tool to call, we run it over MCP, feed the result back, and the model answers
using it.

```bash
uv run python -m week_04.main --target api --agent \
  --provider "GPT-4o mini" \
  --ask "Weather in Moscow (55.75, 37.62)? Then title of post #1."
```

Real run:
```
  -> call get_current_weather({'lat': 55.75, 'lon': 37.62})
  <- {"time": "2026-06-24T08:00", "temperature": 20.0, "windspeed": 8.7, "weathercode": 2}
  -> call get_post({'post_id': 1})
  <- {"id": 1, "title": "sunt aut facere repellat...", ...}

Agent: The current weather in Moscow is 20.0C, wind 8.7 km/h.
The title of post #1 is: "sunt aut facere repellat provident occaecati excepturi optio reprehenderit".
```

## Tests

```bash
uv run pytest week_04 -q
```
`test_mcp_server_api.py` checks the 4 tools are registered with correct required params, plus
live smoke tests against JSONPlaceholder (`list_posts`, `get_post`, `create_post`).

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `uvx not found` | install/update uv; `uvx` ships with uv |
| timeout on first `time` run | first `uvx` run downloads the package, retry (timeout is 60s) |
| invalid JSON args | input must be a JSON object, e.g. `{}` or `{"path": "."}` |
| `remote` unreachable | check network; the endpoint is a public server and may be down |
| `--agent` fails with missing key | set a provider key in `.env` (e.g. `OPENAI_API_KEY`) |

## Demo script

```bash
uv run python -m week_04.main --target own     # our own MCP, stdio (Day 16)
uv run python -m week_04.main --target time    # external MCP (uvx), stdio (Day 16)
uv run python -m week_04.main --target remote  # external MCP (DeepWiki), HTTP (Day 16)
uv run python -m week_04.main --target api     # our API-wrapping MCP, stdio (Day 17)
uv run python -m week_04.main --target api --agent --ask "..."  # LLM uses tool results (Day 17)
```

For Day 16 runs:
- verify `initialize -> ok`
- verify `tools/list -> N tools`
- call at least one tool from the interactive menu

For Day 17:
- show 4 tools on the `api` server
- run the agent and show it calling a tool and using the result in its answer

---

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 16 | MCP connection + interactive tool calls; one shared `ClientSession` over stdio + Streamable HTTP against our own, external stdio, and external remote servers (`own`, `time`, `remote`) | `-m week_04.main`, `--target own\|time\|remote` | `mcp_server.py`, `mcp_client.py`, `targets.py`, `main.py` | done | _link_ |
| 17 | Own MCP server wrapping public APIs (JSONPlaceholder + Open-Meteo), 4 registered tools; LLM agent calls tools and uses results in its answer | `-m week_04.main --target api`, `--agent --ask "..."` | `mcp_server_api.py`, `agent.py`, `targets.py`, `main.py`, `test_mcp_server_api.py` | done | _link_ |

All days share one codebase; the table maps each day to its commands and modules.
