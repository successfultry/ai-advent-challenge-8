import argparse
import asyncio

from week_04.mcp_client import interact
from week_04.targets import TARGETS


def main() -> None:
    parser = argparse.ArgumentParser(description="Day 16 - MCP Connection")
    parser.add_argument("--target", choices=list(TARGETS), default="own")
    args = parser.parse_args()

    try:
        asyncio.run(interact(TARGETS[args.target]()))
    except FileNotFoundError as exc:
        raise SystemExit(f"ERROR: {exc}") from None
    except TimeoutError:
        raise SystemExit("ERROR: MCP server timed out") from None
    except Exception as exc:
        raise SystemExit(f"ERROR: {exc}") from None


if __name__ == "__main__":
    main()
