from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession

from week_04.mcp_client import connect, tool_text
from week_04.targets import Target


@dataclass
class _ServerRuntime:
    stack: AsyncExitStack
    session: ClientSession
    tools: list[Any]
    label: str


@dataclass(frozen=True)
class ToolRoute:
    server_id: str
    bare_name: str


class MultiServerOrchestrator:
    def __init__(self, server_targets: dict[str, Target]) -> None:
        if not server_targets:
            raise ValueError("server_targets cannot be empty")
        self.server_targets = server_targets
        self._servers: dict[str, _ServerRuntime] = {}
        self._routes: dict[str, ToolRoute] = {}
        self._openai_tools: list[dict[str, Any]] = []

    @staticmethod
    def _qualified_name(server_id: str, bare_name: str) -> str:
        return f"{server_id}__{bare_name}"

    async def _open_server(self, server_id: str, target: Target) -> tuple[str, _ServerRuntime]:
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            read, write = await stack.enter_async_context(connect(target))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            tools = (await session.list_tools()).tools
            runtime = _ServerRuntime(stack=stack, session=session, tools=tools, label=target.label)
            return server_id, runtime
        except Exception:
            await stack.aclose()
            raise

    async def __aenter__(self) -> MultiServerOrchestrator:
        tasks = [
            self._open_server(server_id=server_id, target=target)
            for server_id, target in self.server_targets.items()
        ]
        opened_or_errors = await asyncio.gather(*tasks, return_exceptions=True)
        opened: list[tuple[str, _ServerRuntime]] = []
        errors: list[str] = []
        for item in opened_or_errors:
            if isinstance(item, Exception):
                errors.append(str(item))
            else:
                opened.append(item)
        if errors:
            await asyncio.gather(
                *(runtime.stack.aclose() for _, runtime in opened),
                return_exceptions=True,
            )
            raise RuntimeError(
                "failed to initialize orchestrator sessions: " + "; ".join(errors)
            )

        self._servers = dict(opened)
        self._routes = {}
        self._openai_tools = []
        for server_id, runtime in self._servers.items():
            for tool in runtime.tools:
                bare_name = tool.name
                qualified_name = self._qualified_name(server_id, bare_name)
                self._routes[qualified_name] = ToolRoute(server_id=server_id, bare_name=bare_name)
                self._openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": qualified_name,
                            "description": (tool.description or "").strip(),
                            "parameters": tool.inputSchema
                            if isinstance(tool.inputSchema, dict)
                            else {"type": "object", "properties": {}},
                        },
                    }
                )
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        close_tasks = [runtime.stack.aclose() for runtime in self._servers.values()]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        self._servers = {}
        self._routes = {}
        self._openai_tools = []

    @property
    def routes(self) -> dict[str, ToolRoute]:
        return dict(self._routes)

    @property
    def openai_tools(self) -> list[dict[str, Any]]:
        return list(self._openai_tools)

    @property
    def tool_names(self) -> list[str]:
        return [spec["function"]["name"] for spec in self._openai_tools]

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> str:
        route = self._routes.get(qualified_name)
        if route is None:
            raise ValueError(f"unknown qualified tool: {qualified_name}")
        runtime = self._servers.get(route.server_id)
        if runtime is None:
            raise ValueError(f"session missing for server: {route.server_id}")
        result = await runtime.session.call_tool(route.bare_name, arguments=arguments)
        return tool_text(result)
