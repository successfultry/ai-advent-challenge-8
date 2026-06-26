import argparse
import asyncio
import sys

from week_04.agent import run_agent
from week_04.mcp_client import interact
from week_04.targets import TARGETS


def _configure_console() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


def main() -> None:
    _configure_console()
    parser = argparse.ArgumentParser(description="Week 04 - MCP client / agent")
    parser.add_argument("--target", choices=list(TARGETS), default="own")
    parser.add_argument(
        "--agent", action="store_true", help="run the LLM agent instead of the REPL"
    )
    parser.add_argument("--provider", default="GPT-4o mini", help="LLM provider for --agent")
    parser.add_argument("--ask", help="question for the agent (required with --agent)")
    args = parser.parse_args()

    try:
        if args.agent:
            if not args.ask:
                raise SystemExit("ERROR: --agent requires --ask \"your question\"")
            asyncio.run(run_agent(TARGETS[args.target](), args.provider, args.ask))
        else:
            asyncio.run(interact(TARGETS[args.target]()))
    except FileNotFoundError as exc:
        raise SystemExit(f"ERROR: {exc}") from None
    except TimeoutError:
        raise SystemExit("ERROR: MCP server timed out") from None
    except Exception as exc:
        raise SystemExit(f"ERROR: {exc}") from None


if __name__ == "__main__":
    main()
