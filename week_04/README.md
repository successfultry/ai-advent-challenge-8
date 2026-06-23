# Week 04 — MCP, Tools & Tool Orchestration

## Structure

```
week_04/
├── main.py        # thin entrypoint: parse --target and run interactive client
├── mcp_client.py  # shared ClientSession flow + stdio/http transport adapter + call_tool loop
├── mcp_server.py  # baseline FastMCP server with 3 filesystem tools (stdio or --http)
└── targets.py     # target registry (own, time, local_http)
```

No `__init__.py` in `week_04/` (PEP 420 namespace package), same run style as week_02/week_03:
`uv run python -m week_04.main`.

## Day 16 Goal

Connect to MCP, run `initialize`, run `tools/list`, and visibly show returned tools. This week
also adds an interactive `call_tool` loop so tools can be invoked from one CLI.

## Targets

`ClientSession` is identical for every target; only the transport differs:
- `stdio` transport: server runs as a local subprocess over pipes (`own`, `time`)
- `http` transport: client talks streamable HTTP over TCP (`local_http`)

| Target | Transport | Server | External |
|--------|-----------|--------|----------|
| `own` (default) | stdio | `python -m week_04.mcp_server` | no |
| `time` | stdio | `uvx mcp-server-time` | yes |
| `local_http` | http | `python -m week_04.mcp_server --http` (auto-spawned on 127.0.0.1:8000) | no |

`local_http` exercises the same streamable-HTTP transport as a public remote endpoint would,
but reliably: `main` auto-spawns the server in `--http` mode, waits for the port, connects over
`http://127.0.0.1:8000/mcp`, then shuts it down. One command, real HTTP (not stdio).

## Run

```bash
# Baseline local server over stdio (always available)
uv run python -m week_04.main --target own

# External MCP server via uvx, stdio (no Node)
uv run python -m week_04.main --target time

# Own server over real HTTP transport, single command (no external host)
uv run python -m week_04.main --target local_http
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

### own / local_http -> list_files
Args: `{}` (or `{"path": "."}`)
```
D __pycache__
F README.md
F main.py
F mcp_client.py
F mcp_server.py
F targets.py
```

### own / local_http -> read_file
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

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `uvx not found` | install/update uv; `uvx` ships with uv |
| timeout on first `time` run | first `uvx` run downloads the package, retry (timeout is 60s) |
| `local server did not open ...` | port 8000 busy or server failed to start; free the port and retry |
| invalid JSON args | input must be a JSON object, e.g. `{}` or `{"path": "."}` |

### Public remote endpoints (why they were dropped)

Public streamable-HTTP test servers (`*.inevitable.fyi`) were tried but their TLS handshake fails
from this machine: `SSL: UNEXPECTED_EOF_WHILE_READING` (the peer drops the handshake after TCP
connects). `curl` (schannel) and Python (OpenSSL) both fail, while `google.com`/`pypi.org` work —
so it is the remote host or a network/DPI filter, not this code, and it is not fixable client-side.
`local_http` demonstrates the HTTP transport without depending on a flaky external host. This may
be specific to this network/ISP; the endpoint can also simply be down for everyone.

## Demo script

```bash
uv run python -m week_04.main --target own         # stdio, own server
uv run python -m week_04.main --target time        # stdio, external (uvx)
uv run python -m week_04.main --target local_http  # http transport, single command
```

For each run:
- verify `initialize -> ok`
- verify `tools/list -> N tools`
- call at least one tool from the interactive menu

---

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 16 | MCP connection + interactive tool calls; one shared `ClientSession` across stdio and real HTTP transports (`own`, `time`, `local_http`) | `-m week_04.main`, `--target own\|time\|local_http` | `mcp_server.py`, `mcp_client.py`, `targets.py`, `main.py` | done | _link_ |

All days share one codebase; the table maps each day to its commands and modules.
