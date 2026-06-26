from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("places", log_level="ERROR")

_FSQ_URL = "https://places-api.foursquare.com/places/search"
_FSQ_VERSION = "2025-06-17"
_FSQ_FIELDS = "name,location,categories,distance,tel,website"
_TIMEOUT = httpx.Timeout(15.0)
_OUTPUTS_DIR = Path(__file__).parent / "places_outputs"
_SAFE_FILENAME = re.compile(r"^[\w\-. ]+$")


def _fsq_key() -> str:
    key = os.environ.get("FOURSQUARE_API_KEY", "")
    if not key:
        raise RuntimeError("FOURSQUARE_API_KEY env var is not set")
    return key


def _parse_place(place: dict[str, Any]) -> dict[str, Any]:
    loc = place.get("location") or {}
    cats = [
        category.get("name", "")
        for category in (place.get("categories") or [])
        if category.get("name")
    ]
    return {
        "name": place.get("name", ""),
        "address": loc.get("address", ""),
        "locality": loc.get("locality", ""),
        "country": loc.get("country", ""),
        "categories": cats,
        "distance_m": place.get("distance"),
        "tel": place.get("tel", ""),
        "website": place.get("website", ""),
    }


@mcp.tool(
    description=(
        "Search for real places via Foursquare Places API. "
        "Returns JSON with venues including name, address, categories, distance, "
        "tel, and website. "
        "Use `near` for a city/locality name (e.g. 'Tokyo', 'Saint Petersburg'). "
        "Use `query` to specify type of place (e.g. 'sushi', 'italian restaurant'). "
        "sort: RELEVANCE | DISTANCE. "
        "Rating/popularity/price values are Premium and are not returned. "
        "min_price/max_price filters are supported: 1=$ 2=$$ 3=$$$ 4=$$$$."
    )
)
async def search_places(
    near: str,
    query: str = "restaurant",
    limit: int = 10,
    sort: str = "RELEVANCE",
    open_now: bool = False,
    min_price: int | None = None,
    max_price: int | None = None,
) -> str:
    near = near.strip()
    query = query.strip()
    sort = sort.strip().upper()
    if not near:
        return json.dumps({"error": "near must be a non-empty string"})
    if not query:
        return json.dumps({"error": "query must be a non-empty string"})
    if not (1 <= limit <= 50):
        return json.dumps({"error": "limit must be between 1 and 50"})
    if sort not in {"RELEVANCE", "DISTANCE"}:
        return json.dumps({"error": "sort must be RELEVANCE or DISTANCE"})

    params: dict[str, str | int] = {
        "near": near,
        "query": query,
        "limit": limit,
        "sort": sort,
        "fields": _FSQ_FIELDS,
    }
    if open_now:
        params["open_now"] = "true"
    if min_price is not None:
        params["min_price"] = min_price
    if max_price is not None:
        params["max_price"] = max_price

    try:
        key = _fsq_key()
    except RuntimeError as exc:
        return json.dumps({"error": str(exc)})

    headers = {
        "Authorization": f"Bearer {key}",
        "X-Places-Api-Version": _FSQ_VERSION,
        "accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_FSQ_URL, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return json.dumps(
            {
                "error": (
                    f"Foursquare API error: {exc.response.status_code} "
                    f"{exc.response.text[:200]}"
                )
            }
        )
    except ValueError:
        return json.dumps({"error": "Foursquare returned non-JSON body"})
    except httpx.HTTPError as exc:
        return json.dumps({"error": f"Foursquare request failed: {exc}"})

    results = data.get("results") or []
    places = [_parse_place(place) for place in results]
    return json.dumps(
        {"near": near, "query": query, "count": len(places), "places": places}
    )


@mcp.tool(
    description=(
        "Build a markdown report from search_places output. "
        "data_json must be the JSON string returned by search_places. "
        "top_n: how many places to include. "
        "max_distance_m: optional filter - drop places farther than this many metres. "
        "Distance is measured from the geocoded center of `near`, not from the user. "
        "Returns JSON with report_markdown ready to save."
    )
)
def build_report(
    data_json: str,
    top_n: int = 5,
    max_distance_m: int | None = None,
) -> str:
    try:
        data = json.loads(data_json)
    except (json.JSONDecodeError, ValueError):
        return json.dumps({"error": "data_json is not valid JSON"})

    if "error" in data:
        return json.dumps({"error": data["error"]})

    places: list[dict[str, Any]] = data.get("places") or []
    near: str = data.get("near", "")
    query: str = data.get("query", "")

    if max_distance_m is not None:
        places = [
            place
            for place in places
            if (place.get("distance_m") or 0) <= max_distance_m
        ]

    places = sorted(places, key=lambda place: place.get("distance_m") or 0)
    selected = places[: max(0, top_n)]

    lines: list[str] = [f"## Places: {query} near {near}", ""]
    for i, place in enumerate(selected, 1):
        addr_parts = [place["address"], place["locality"], place["country"]]
        addr = ", ".join(part for part in addr_parts if part)
        cats = " / ".join(place["categories"]) if place["categories"] else "-"
        dist = (
            f"{place['distance_m']} m" if place.get("distance_m") is not None else "-"
        )
        tel = place["tel"] or "-"
        web = place["website"] or "-"
        lines.append(f"{i}. **{place['name']}** - {addr}")
        lines.append(
            f"   Categories: {cats} | Distance: {dist} | Tel: {tel} | Web: {web}"
        )
        lines.append("")

    lines.append("---")
    lines.append(f"Showing {len(selected)} of {len(data.get('places') or [])} places found.")
    lines.append("")

    return json.dumps(
        {
            "shown": len(selected),
            "total": len(data.get("places") or []),
            "near": near,
            "query": query,
            "report_markdown": "\n".join(lines),
        }
    )


@mcp.tool(
    description=(
        "Save text content to a file in week_04/places_outputs/. "
        "content: the text to write (e.g. a markdown report). "
        "filename: file name only, no path separators. Defaults to places_report.md. "
        "Returns JSON with ok, path, and bytes written."
    )
)
def save_to_file(
    content: str,
    filename: str = "places_report.md",
) -> str:
    filename = filename.strip()
    if not filename:
        return json.dumps({"error": "filename must not be empty"})
    if filename in {".", ".."}:
        return json.dumps({"error": "filename must not be '.' or '..'"})
    if ".." in filename or "/" in filename or "\\" in filename:
        return json.dumps({"error": "filename must not contain path separators or '..'"})
    if not _SAFE_FILENAME.match(filename):
        return json.dumps({"error": "filename contains invalid characters"})

    out_dir = _OUTPUTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / filename
    dest.write_text(content, encoding="utf-8")
    try:
        rel_path = dest.relative_to(Path(__file__).resolve().parents[1])
    except ValueError:
        rel_path = dest
    return json.dumps(
        {"ok": True, "path": rel_path.as_posix(), "bytes": len(content.encode())}
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
