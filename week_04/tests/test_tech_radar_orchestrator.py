from __future__ import annotations

from types import SimpleNamespace

import pytest

from week_04.orchestrator import MultiServerOrchestrator, ToolRoute, _ServerRuntime
from week_04.targets import ORCHESTRATION_PROFILES


class _FakeSession:
    async def call_tool(self, name: str, arguments: dict) -> dict:
        return {"text": f"{name}:{arguments}"}


@pytest.mark.asyncio
async def test_qualified_route_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("week_04.orchestrator.tool_text", lambda result: result["text"])
    orchestrator = MultiServerOrchestrator({"github": SimpleNamespace(), "pypi": SimpleNamespace()})
    orchestrator._servers = {
        "github": _ServerRuntime(
            stack=SimpleNamespace(aclose=lambda: None),  # type: ignore[arg-type]
            session=_FakeSession(),  # type: ignore[arg-type]
            tools=[],
            label="github",
        )
    }
    orchestrator._routes = {
        "github__get_repo": ToolRoute(server_id="github", bare_name="get_repo"),
    }

    text = await orchestrator.call_tool("github__get_repo", {"full_name": "pydantic/pydantic"})
    assert text == "get_repo:{'full_name': 'pydantic/pydantic'}"


@pytest.mark.asyncio
async def test_unknown_qualified_tool_raises() -> None:
    orchestrator = MultiServerOrchestrator({"github": SimpleNamespace()})
    orchestrator._servers = {}
    orchestrator._routes = {}
    with pytest.raises(ValueError, match="unknown qualified tool"):
        await orchestrator.call_tool("missing__tool", {})


def test_radar_profile_includes_required_servers() -> None:
    assert ORCHESTRATION_PROFILES["tech_radar"] == ["github", "pypi", "radar", "reports"]

