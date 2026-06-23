from pathlib import Path

from mcp.server.fastmcp import FastMCP

SCOPE = Path("week_04")

mcp = FastMCP("week04-fs", log_level="ERROR")


def _resolve(path: str) -> Path | None:
    target = (SCOPE / path).resolve()
    if not str(target).startswith(str(SCOPE.resolve())):
        return None
    return target


@mcp.tool(description="List files and directories under a week_04-relative path.")
def list_files(path: str = ".") -> str:
    target = _resolve(path)
    if target is None:
        return "Error: path outside week_04"
    if not target.exists():
        return f"Path does not exist: {path}"
    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
    return "\n".join(f"{'F' if e.is_file() else 'D'} {e.name}" for e in entries) or "(empty)"


@mcp.tool(description="Read a text file inside week_04.")
def read_file(path: str) -> str:
    target = _resolve(path)
    if target is None:
        return "Error: path outside week_04"
    if not target.is_file():
        return f"Not a file: {path}"
    return target.read_text(encoding="utf-8", errors="replace")


@mcp.tool(description="Write text to a file inside week_04 (creates parent dirs).")
def write_file(path: str, content: str) -> str:
    target = _resolve(path)
    if target is None:
        return "Error: path outside week_04"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Written {len(content)} chars to {path}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
