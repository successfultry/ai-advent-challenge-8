import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("api-tools-server", log_level="ERROR")

_TIMEOUT = httpx.Timeout(15.0)
_JP = "https://jsonplaceholder.typicode.com"
_METEO = "https://api.open-meteo.com/v1/forecast"


@mcp.tool(description="List posts from JSONPlaceholder. Returns up to `limit` items.")
async def list_posts(limit: int = 10) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_JP}/posts")
            r.raise_for_status()
            posts = r.json()
            return [
                {"id": p["id"], "title": p["title"], "body": p["body"], "userId": p["userId"]}
                for p in posts[:limit]
            ]
    except httpx.HTTPError as exc:
        return [{"error": str(exc)}]


@mcp.tool(description="Get a single post by ID from JSONPlaceholder.")
async def get_post(post_id: int) -> dict:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_JP}/posts/{post_id}")
            r.raise_for_status()
            p = r.json()
            return {"id": p["id"], "title": p["title"], "body": p["body"], "userId": p["userId"]}
    except httpx.HTTPStatusError as exc:
        return {"error": f"HTTP {exc.response.status_code}"}
    except httpx.HTTPError as exc:
        return {"error": str(exc)}


@mcp.tool(description="Create a post on JSONPlaceholder (fake: always returns id=101).")
async def create_post(title: str, body: str, userId: int = 1) -> dict:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(
                f"{_JP}/posts", json={"title": title, "body": body, "userId": userId}
            )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as exc:
        return {"error": str(exc)}


@mcp.tool(description="Get current weather for given coordinates (lat/lon) via Open-Meteo.")
async def get_current_weather(lat: float, lon: float) -> dict:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(
                _METEO,
                params={"latitude": lat, "longitude": lon, "current_weather": "true"},
            )
            r.raise_for_status()
            data = r.json()
        cw = data.get("current_weather")
        if not cw:
            return {"error": "no current_weather in response"}
        return {
            "time": cw["time"],
            "temperature": cw["temperature"],
            "windspeed": cw["windspeed"],
            "weathercode": cw["weathercode"],
        }
    except httpx.HTTPError as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
