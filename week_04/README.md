# Week 04 — MCP, Tools & Tool Orchestration

## Structure

```
week_04/
├── main.py        # thin entrypoint: parse --target and run interactive client
├── mcp_client.py  # ClientSession flow over stdio/http + interactive call_tool loop
├── mcp_server.py  # baseline FastMCP server with 3 filesystem tools (stdio)
└── targets.py     # target registry (own, time, remote)
```

No `__init__.py` in `week_04/` (PEP 420 namespace package), same run style as week_02/week_03:
`uv run python -m week_04.main`.

## Day 16 Goal

Connect to MCP, run `initialize`, run `tools/list`, and visibly show returned tools. This week
also adds an interactive `call_tool` loop so tools can be invoked from one CLI.

## Targets

All targets use the same `ClientSession`; the difference is transport + whose server it is:

| Target | Server | Transport | Whose | Requires |
|--------|--------|-----------|-------|----------|
| `own` (default) | `python -m week_04.mcp_server` (week04-fs, 3 file tools) | stdio | ours | Python only |
| `time` | `uvx mcp-server-time` | stdio | external (Anthropic) | uvx (ships with uv) |
| `remote` | `https://mcp.deepwiki.com/mcp` (DeepWiki, 3 tools) | Streamable HTTP | external (Devin) | network |

## Run

```bash
# Our own MCP server (stdio)
uv run python -m week_04.main --target own

# External MCP server via uvx (stdio, no Node)
uv run python -m week_04.main --target time

# External remote MCP over HTTP (DeepWiki)
uv run python -m week_04.main --target remote
```

First-time setup:

```bash
uv add "mcp[cli]"
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

## Example calls (real output)

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

### remote -> ask_question
Args: `{"repoName": "facebook/react", "question": "What is the entry point?"}`

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `uvx not found` | install/update uv; `uvx` ships with uv |
| timeout on first `time` run | first `uvx` run downloads the package, retry (timeout is 60s) |
| invalid JSON args | input must be a JSON object, e.g. `{}` or `{"path": "."}` |
| `remote` unreachable | check network; the endpoint is a public server and may be down |

## Demo script

```bash
uv run python -m week_04.main --target own     # our own MCP, stdio
uv run python -m week_04.main --target time    # external MCP (uvx), stdio
uv run python -m week_04.main --target remote  # external MCP (DeepWiki), HTTP
```

For each run:
- verify `initialize -> ok`
- verify `tools/list -> N tools`
- call at least one tool from the interactive menu

---

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 16 | MCP connection + interactive tool calls; one shared `ClientSession` over stdio + Streamable HTTP against our own, external stdio, and external remote servers (`own`, `time`, `remote`) | `-m week_04.main`, `--target own\|time\|remote` | `mcp_server.py`, `mcp_client.py`, `targets.py`, `main.py` | done | _link_ |

All days share one codebase; the table maps each day to its commands and modules.
