import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any, Literal

from mcp import ClientSession

from shared.client import get_client
from week_04.mcp_client import connect, tool_text
from week_04.targets import market_watch

_SYSTEM = (
    "You are a prediction-market analyst. Use only facts present in the aggregate JSON: "
    "markets, probabilities, volumes, and top_movers. Never invent markets, prices, "
    "volumes, or movement. Render probabilities as percentages, e.g. 0.42 becomes 42%. "
    "Highlight the highest-volume markets and biggest movers with direction. Be dense, "
    "readable, and explicit when mover data is unavailable."
)
Lang = Literal["en", "ru", "both"]


async def run_watcher(
    provider: str,
    interval_s: int = 60,
    window: str = "1h",
    cycles: int | None = None,
    use_llm: bool = True,
    lang: Lang = "both",
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
                await _run_cycle(session, client, model, window, use_llm, lang)
                if cycles is not None and cycle >= cycles:
                    break
                await asyncio.sleep(interval_s)


async def _run_cycle(
    session: ClientSession,
    client: Any,
    model: str | None,
    window: str,
    use_llm: bool,
    lang: Lang,
) -> None:
    collected = await session.call_tool("collect_now", arguments={})
    collected_data = _parse_json_text(tool_text(collected))
    summary_result = await session.call_tool(
        "build_summary", arguments={"window": window, "top_n": 20}
    )
    summary = _parse_json_text(tool_text(summary_result))

    fallback = summary.get("text") or "No market summary available."
    text = fallback
    if use_llm and client is not None and model is not None:
        text = await _phrase_summary(client, model, summary, fallback, lang)

    print(f"[{datetime.now(UTC).isoformat()}] Market Watch")
    print(f"collect_now: {collected_data}")
    print(text)
    print()


async def _phrase_summary(
    client: Any,
    model: str,
    summary: dict,
    fallback: str,
    lang: Lang,
) -> str:
    language_instruction = _language_instruction(lang)
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"{language_instruction}\n\n"
                "Write a structured markdown market summary from this aggregate JSON.\n"
                "For each requested language, use this exact structure:\n"
                "- one headline line with market_count and window\n"
                "- 'Top markets' with up to 10 bullets: question - outcome probability% (vol)\n"
                "- 'Top movers' with up to 3 bullets: question - outcome "
                "from% -> to% (delta +/-x.x pts)\n"
                "- if there are no movers, say that explicitly\n\n"
                f"{json.dumps(summary, ensure_ascii=False)}"
            ),
        },
    ]
    try:
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            messages=messages,
            temperature=0,
        )
    except Exception as exc:
        return f"{fallback} (LLM unavailable: {exc})"
    return resp.choices[0].message.content or fallback


def _language_instruction(lang: Lang) -> str:
    # Bilingual output is a useful demo, but doubles output tokens in a 24/7 loop.
    if lang == "both":
        return (
            'Return two sections: "## English" and then "## Русский". '
            "Use the same facts in both sections, with natural Russian translation."
        )
    if lang == "ru":
        return 'Return only one section: "## Русский".'
    return 'Return only one section: "## English".'


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
    parser.add_argument(
        "--lang",
        choices=("en", "ru", "both"),
        default="both",
        help="LLM summary language: en, ru, or both",
    )
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
                lang=args.lang,
            )
        )
    except KeyboardInterrupt:
        raise SystemExit("Stopped.") from None
    except Exception as exc:
        raise SystemExit(f"ERROR: {exc}") from None


if __name__ == "__main__":
    main()
