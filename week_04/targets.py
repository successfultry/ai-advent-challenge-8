import shutil
import sys
from dataclasses import dataclass
from typing import Literal

from mcp import StdioServerParameters

REMOTE_URL = "https://mcp.deepwiki.com/mcp"


@dataclass(frozen=True)
class Target:
    label: str
    kind: Literal["stdio", "http"]
    params: StdioServerParameters | None = None
    url: str | None = None


def own() -> Target:
    return Target(
        label="own Python MCP server (week04-fs)",
        kind="stdio",
        params=StdioServerParameters(command=sys.executable, args=["-m", "week_04.mcp_server"]),
    )


def time() -> Target:
    uvx = shutil.which("uvx")
    if uvx is None:
        raise FileNotFoundError("uvx not found. It ships with uv.")
    return Target(
        label="mcp-server-time via uvx (external)",
        kind="stdio",
        params=StdioServerParameters(command=uvx, args=["mcp-server-time"]),
    )


def remote() -> Target:
    return Target(
        label=f"DeepWiki remote MCP over Streamable HTTP ({REMOTE_URL})",
        kind="http",
        url=REMOTE_URL,
    )


TARGETS = {"own": own, "time": time, "remote": remote}
