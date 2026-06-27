from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("tech-radar-pypi", log_level="ERROR")

_TIMEOUT = httpx.Timeout(20.0)


def _json_error(message: str, **extra: Any) -> str:
    payload: dict[str, Any] = {"error": message}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


async def _package_json(name: str) -> dict[str, Any]:
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        return {
            "error": f"pypi http {exc.response.status_code}",
            "package": name,
            "details": exc.response.text[:200],
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {"error": f"pypi request failed: {exc}", "package": name}


def _latest_upload_time(files: list[dict[str, Any]]) -> str | None:
    values = [f.get("upload_time_iso_8601") for f in files if f.get("upload_time_iso_8601")]
    if not values:
        return None
    return max(values)


def _safe_iso_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@mcp.tool(description="Get package metadata from PyPI.")
async def get_package(name: str) -> str:
    name = name.strip()
    if not name:
        return _json_error("name must be a non-empty string")
    data = await _package_json(name)
    if "error" in data:
        return json.dumps(data, ensure_ascii=False)
    info = data.get("info") or {}
    payload = {
        "name": info.get("name"),
        "summary": info.get("summary"),
        "version": info.get("version"),
        "requires_python": info.get("requires_python"),
        "license": info.get("license"),
        "classifiers": info.get("classifiers") or [],
        "project_urls": info.get("project_urls") or {},
        "error": None,
    }
    return json.dumps(payload, ensure_ascii=False)


@mcp.tool(description="Get latest release timestamps for a package from PyPI.")
async def recent_releases(name: str, limit: int = 10) -> str:
    name = name.strip()
    if not name:
        return _json_error("name must be a non-empty string")
    limit = max(1, min(limit, 30))
    data = await _package_json(name)
    if "error" in data:
        return json.dumps(data, ensure_ascii=False)

    releases = data.get("releases") or {}
    rows: list[dict[str, Any]] = []
    for version, files in releases.items():
        if not isinstance(files, list):
            continue
        latest = _latest_upload_time(files)
        rows.append({"version": version, "uploaded_at": latest})

    rows.sort(
        key=lambda row: _safe_iso_to_dt(row.get("uploaded_at")),
        reverse=True,
    )
    payload = {"name": name, "items": rows[:limit], "error": None}
    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="stdio")

