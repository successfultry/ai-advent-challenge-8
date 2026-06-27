from __future__ import annotations

import json
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("tech-radar-github", log_level="ERROR")

_TIMEOUT = httpx.Timeout(20.0)
_BASE = "https://api.github.com"


def _json_error(message: str, **extra: Any) -> str:
    payload: dict[str, Any] = {"error": message}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


async def _get(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        return {
            "error": f"github http {exc.response.status_code}",
            "details": exc.response.text[:200],
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {"error": f"github request failed: {exc}"}


@mcp.tool(description="Search GitHub repositories by query. Returns repository candidates.")
async def search_repos(query: str, limit: int = 10) -> str:
    query = query.strip()
    if not query:
        return _json_error("query must be a non-empty string")
    limit = max(1, min(limit, 20))
    data = await _get(
        f"{_BASE}/search/repositories",
        params={"q": query, "per_page": limit, "sort": "stars", "order": "desc"},
    )
    if "error" in data:
        return _json_error(data["error"], query=query, details=data.get("details"))

    items = data.get("items") or []
    results = [
        {
            "full_name": item.get("full_name"),
            "name": item.get("name"),
            "owner": (item.get("owner") or {}).get("login"),
            "description": item.get("description"),
            "stargazers_count": item.get("stargazers_count"),
            "language": item.get("language"),
            "updated_at": item.get("updated_at"),
            "html_url": item.get("html_url"),
        }
        for item in items
    ]
    return json.dumps({"query": query, "count": len(results), "items": results}, ensure_ascii=False)


@mcp.tool(description="Get repository metadata by full name (owner/repo).")
async def get_repo(full_name: str) -> str:
    full_name = full_name.strip()
    if "/" not in full_name:
        return _json_error("full_name must look like owner/repo", full_name=full_name)
    data = await _get(f"{_BASE}/repos/{full_name}")
    if "error" in data:
        return _json_error(data["error"], full_name=full_name, details=data.get("details"))
    payload = {
        "full_name": data.get("full_name"),
        "description": data.get("description"),
        "stargazers_count": data.get("stargazers_count"),
        "forks_count": data.get("forks_count"),
        "open_issues_count": data.get("open_issues_count"),
        "language": data.get("language"),
        "topics": data.get("topics") or [],
        "updated_at": data.get("updated_at"),
        "created_at": data.get("created_at"),
        "default_branch": data.get("default_branch"),
        "archived": data.get("archived"),
    }
    return json.dumps(payload, ensure_ascii=False)


@mcp.tool(description="Get README excerpt for a GitHub repository.")
async def get_readme_excerpt(full_name: str, max_chars: int = 1500) -> str:
    full_name = full_name.strip()
    if "/" not in full_name:
        return _json_error("full_name must look like owner/repo", full_name=full_name)
    max_chars = max(200, min(max_chars, 5000))
    headers = {
        "Accept": "application/vnd.github.raw+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
            response = await client.get(f"{_BASE}/repos/{full_name}/readme")
            response.raise_for_status()
            text = response.text
    except httpx.HTTPStatusError as exc:
        return _json_error(
            f"github readme http {exc.response.status_code}",
            full_name=full_name,
            details=exc.response.text[:200],
        )
    except httpx.HTTPError as exc:
        return _json_error(f"github readme request failed: {exc}", full_name=full_name)

    excerpt = text[:max_chars]
    return json.dumps(
        {"full_name": full_name, "max_chars": max_chars, "excerpt": excerpt},
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")

