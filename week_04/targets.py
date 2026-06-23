import shutil
import sys
from dataclasses import dataclass
from typing import Literal

from mcp import StdioServerParameters

LOCAL_HTTP_URL = "http://127.0.0.1:8000/mcp"


@dataclass(frozen=True)
class Target:
    label: str
    kind: Literal["stdio", "http"]
    params: StdioServerParameters | None = None
    url: str | None = None
    spawn: list[str] | None = None


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


def local_http() -> Target:
    return Target(
        label=f"own server over local HTTP ({LOCAL_HTTP_URL})",
        kind="http",
        url=LOCAL_HTTP_URL,
        spawn=[sys.executable, "-m", "week_04.mcp_server", "--http"],
    )


TARGETS = {"own": own, "time": time, "local_http": local_http}
