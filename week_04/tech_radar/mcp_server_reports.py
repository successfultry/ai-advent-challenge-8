from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("tech-radar-reports", log_level="ERROR")

_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "tech_radar_outputs"
_SAFE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _safe_slug(slug: str) -> str | None:
    value = slug.strip()
    if not value:
        return None
    if "/" in value or "\\" in value or ".." in value:
        return None
    if not _SAFE.fullmatch(value):
        return None
    return value


@mcp.tool(description="Save a markdown report inside week_04/tech_radar_outputs.")
def save_report(content: str, slug: str) -> str:
    safe = _safe_slug(slug)
    if safe is None:
        return _json({"error": "invalid slug; use letters, numbers, dot, underscore, hyphen"})
    filename = safe if safe.endswith(".md") else f"{safe}.md"
    _OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _OUTPUTS_DIR / filename
    path.write_text(content, encoding="utf-8")
    root = Path(__file__).resolve().parent.parent
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = Path("tech_radar_outputs") / filename
    return _json({"ok": True, "path": str(rel).replace("\\", "/"), "bytes": len(content.encode())})


@mcp.tool(description="List saved reports from week_04/tech_radar_outputs.")
def list_reports() -> str:
    if not _OUTPUTS_DIR.exists():
        return _json({"count": 0, "reports": []})
    files = sorted([p.name for p in _OUTPUTS_DIR.iterdir() if p.is_file()])
    return _json({"count": len(files), "reports": files})


@mcp.tool(description="Load a saved report by slug from week_04/tech_radar_outputs.")
def load_report(slug: str) -> str:
    safe = _safe_slug(slug)
    if safe is None:
        return _json({"error": "invalid slug"})
    filename = safe if safe.endswith(".md") else f"{safe}.md"
    path = _OUTPUTS_DIR / filename
    if not path.exists() or not path.is_file():
        return _json({"error": f"report not found: {filename}"})
    return path.read_text(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    mcp.run(transport="stdio")



