import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from mcp import ClientSession

from shared.client import get_client
from week_04.mcp_client import connect, tool_text
from week_04.targets import market_watch

_SYSTEM = (
    "You are a prediction-market analyst. Be concise. "
    "Mention notable markets, prices, and movers when available."
)


async def run_watcher(
    provider: str,
    interval_s: int = 60,
    window: str = "1h",
    cycles: int | None = None,
    use_llm: bool = True,
) -> None:
    client = model = None
    if use_llm:
        client, model = get_client(provider)

    target = market_watch()
    print(f"Target: {target.label}")
    print(f"Mode: {'LLM summary' if use_llm else 'deterministic summary'}")
    async with connect(target) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            print(f"tools available: {[tool.name for tool in tools]}\n")

            cycle = 0
            while cycles is None or cycle < cycles:
                cycle += 1
                await _run_cycle(session, client, model, window, use_llm)
                if cycles is not None and cycle >= cycles:
                    break
                await asyncio.sleep(interval_s)


async def _run_cycle(
    session: ClientSession,
    client: Any,
    model: str | None,
    window: str,
    use_llm: bool,
) -> None:
    collected = await session.call_tool("collect_now", arguments={})
    collected_data = _parse_json_text(tool_text(collected))
    summary_result = await session.call_tool("build_summary", arguments={"window": window})
    summary = _parse_json_text(tool_text(summary_result))

    fallback = summary.get("text") or "No market summary available."
    text = fallback
    if use_llm and client is not None and model is not None:
        text = await _phrase_summary(client, model, summary, fallback)

    print(f"[{datetime.now(UTC).isoformat()}] Market Watch")
    print(f"collect_now: {collected_data}")
    print(text)
    print()


async def _phrase_summary(client: Any, model: str, summary: dict, fallback: str) -> str:
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                "Write a 2-3 sentence summary from this aggregate JSON:\n"
                f"{json.dumps(summary, ensure_ascii=False)}"
            ),
        },
    ]
    try:
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            messages=messages,
        )
    except Exception as exc:
        return f"{fallback} (LLM unavailable: {exc})"
    return resp.choices[0].message.content or fallback


def _parse_json_text(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}
    return data if isinstance(data, dict) else {"value": data}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Day 18 Market Watch agent loop")
    parser.add_argument("--provider", default="GPT-4o mini", help="LLM provider for summaries")
    parser.add_argument("--interval", type=int, default=60, help="seconds between cycles")
    parser.add_argument("--window", default="1h", help="summary window, e.g. all, 1h, 24h, 7d")
    parser.add_argument("--cycles", type=int, help="finite cycle count for demos/tests")
    parser.add_argument("--no-llm", action="store_true", help="use deterministic tool text only")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        asyncio.run(
            run_watcher(
                provider=args.provider,
                interval_s=max(1, args.interval),
                window=args.window,
                cycles=args.cycles,
                use_llm=not args.no_llm,
            )
        )
    except KeyboardInterrupt:
        raise SystemExit("Stopped.") from None
    except Exception as exc:
        raise SystemExit(f"ERROR: {exc}") from None


if __name__ == "__main__":
    main()
