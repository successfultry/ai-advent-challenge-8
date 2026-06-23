import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import TextContent

from week_04.targets import Target

TIMEOUT = 60


@asynccontextmanager
async def _connect(target: Target) -> AsyncIterator[tuple[Any, Any]]:
    if target.kind == "stdio":
        if target.params is None:
            raise ValueError("stdio target must define params")
        async with stdio_client(target.params) as (read, write):
            yield read, write
        return

    if target.url is None:
        raise ValueError("http target must define url")
    try:
        async with streamablehttp_client(target.url) as (read, write, _):
            yield read, write
    except Exception as exc:
        raise RuntimeError(f"remote MCP endpoint unreachable: {target.url}") from exc


def _print_tools(tools: list[Any]) -> None:
    print("Available tools:")
    for idx, tool in enumerate(tools, start=1):
        desc = (tool.description or "").strip()
        print(f"  [{idx}] {tool.name}{f': {desc}' if desc else ''}")


def _prompt_args(schema: dict[str, Any]) -> dict[str, Any]:
    print("Input schema:")
    print(json.dumps(schema, indent=2, ensure_ascii=True))
    while True:
        raw = input("Args as JSON (empty = {}): ").strip()
        if raw == "":
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON: {exc}")
            continue
        if not isinstance(parsed, dict):
            print("Args must be a JSON object.")
            continue
        return parsed


async def _call_tool(session: ClientSession, tool_name: str, arguments: dict[str, Any]) -> None:
    result = await session.call_tool(tool_name, arguments=arguments)
    prefix = "TOOL ERROR: " if result.isError else ""
    for block in result.content:
        if isinstance(block, TextContent):
            print(f"{prefix}{block.text}")
        else:
            print(f"{prefix}[{type(block).__name__}]")


async def _repl(session: ClientSession, tools: list[Any]) -> None:
    while True:
        _print_tools(tools)
        choice = input("Pick a tool number (or 'q' to quit): ").strip().lower()
        if choice == "q":
            return
        if not choice.isdigit():
            print("Pick a numeric tool index.\n")
            continue
        idx = int(choice) - 1
        if idx < 0 or idx >= len(tools):
            print("Tool index out of range.\n")
            continue

        tool = tools[idx]
        schema = tool.inputSchema if isinstance(tool.inputSchema, dict) else {}
        arguments = _prompt_args(schema)
        await _call_tool(session, tool.name, arguments)
        print()


async def interact(target: Target) -> None:
    print(f"Target: {target.label}", flush=True)
    async with _connect(target) as (read, write):
        async with ClientSession(read, write) as session:
            async with asyncio.timeout(TIMEOUT):
                init = await session.initialize()
                info = init.serverInfo
                print(f"initialize -> ok  ({info.name} v{info.version})")
                result = await session.list_tools()

            tools = result.tools
            print(f"tools/list -> {len(tools)} tools")
            print("Connection: OK\n")
            if not tools:
                print("(no tools returned)")
                return

            await _repl(session, tools)
