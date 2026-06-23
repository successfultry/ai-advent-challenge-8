# Week 04 — MCP, Tools & Tool Orchestration

## Structure

```
week_04/
├── main.py        # thin entrypoint: parse --target and run interactive client
├── mcp_client.py  # shared ClientSession flow + stdio/http transport adapter + call_tool loop
├── mcp_server.py  # baseline local FastMCP server with 3 filesystem tools
└── targets.py     # target registry (own, time, remote)
```

No `__init__.py` in `week_04/` (PEP 420 namespace package), same run style as week_02/week_03:
`uv run python -m week_04.main`.

## Day 16 Goal

Connect to MCP, run `initialize`, run `tools/list`, and visibly show returned tools. This week
also adds an interactive `call_tool` loop for local testing from one CLI.

## Targets

`ClientSession` is shared across all targets; only transport differs:
- `stdio` transport: local subprocess (`own`, `time`)
- `http` transport: remote streamable HTTP endpoint (`remote`)

| Target | Transport | Server | External |
|--------|-----------|--------|----------|
| `own` (default) | stdio | `python -m week_04.mcp_server` | no |
| `time` | stdio | `uvx mcp-server-time` | yes |
| `remote` | http | `https://everything.mcp.inevitable.fyi/mcp` | yes |

## Run

```bash
# Baseline local server (always available)
uv run python -m week_04.main --target own

# External MCP server via uvx (no Node)
uv run python -m week_04.main --target time

# External public endpoint (zero install, depends on remote uptime)
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

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `uvx not found` | install/update uv; `uvx` ships with uv |
| timeout on first `time` run | first `uvx` run downloads package, retry (timeout is 60s) |
| remote target fails | public endpoint uptime issue; use `own` or `time` |
| invalid JSON args | input must be JSON object, e.g. `{}` or `{\"path\": \".\"}` |

## Demo script

```bash
uv run python -m week_04.main --target own
uv run python -m week_04.main --target time
uv run python -m week_04.main --target remote
```

For each run:
- verify `initialize -> ok`
- verify `tools/list -> N tools`
- call at least one tool from the interactive menu

---

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 16 | MCP connection + interactive tool calls with shared client across stdio/http targets (`own`, `time`, `remote`) | `-m week_04.main`, `--target own\|time\|remote` | `mcp_server.py`, `mcp_client.py`, `targets.py`, `main.py` | done | _link_ |

All days share one codebase; the table maps each day to its commands and modules.
