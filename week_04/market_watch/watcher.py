import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any, Literal

from mcp import ClientSession

from shared.client import get_client
from week_04.market_watch.notify import send_telegram_message
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
    llm_payload: dict[str, Any] | None = None
    text = fallback
    if use_llm and client is not None and model is not None:
        llm_payload = await _phrase_summary(client, model, summary, lang)
        if llm_payload is None:
            llm_payload = _build_fallback_payload(summary, lang)
            text = _console_text_from_payload(
                llm_payload,
                window=str(summary.get("window", window)),
                market_count=int(summary.get("market_count", 0)),
                lang=lang,
            )
            text = f"{text}\n\n(LLM payload invalid; deterministic fallback used.)"
        else:
            text = _console_text_from_payload(
                llm_payload,
                window=str(summary.get("window", window)),
                market_count=int(summary.get("market_count", 0)),
                lang=lang,
            )

    print(f"[{datetime.now(UTC).isoformat()}] Market Watch")
    print(f"collect_now: {collected_data}")
    print(text)
    if llm_payload is not None:
        telegram_error = await send_telegram_message(
            llm_payload,
            window=str(summary.get("window", window)),
            market_count=int(summary.get("market_count", 0)),
            lang=lang,
        )
    else:
        telegram_error = None
    if telegram_error:
        print(f"[telegram] send failed: {telegram_error}")
    print()


async def _phrase_summary(
    client: Any,
    model: str,
    summary: dict,
    lang: Lang,
) -> dict[str, Any] | None:
    messages = [{"role": "system", "content": _SYSTEM}]
    base_prompt = _llm_prompt(summary, lang)
    retry_prompts = [base_prompt, f"{base_prompt}\n\nReturn valid JSON only matching the schema."]
    for prompt in retry_prompts:
        messages = [messages[0], {"role": "user", "content": prompt}]
        try:
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
            )
        except Exception:
            continue
        content = resp.choices[0].message.content or ""
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            continue
        if _validate_payload(parsed, lang):
            return parsed
    return None


def _llm_prompt(summary: dict[str, Any], lang: Lang) -> str:
    language_instruction = _language_instruction(lang)
    return (
        f"{language_instruction}\n\n"
        "Return only valid JSON (no markdown, no prose outside JSON).\n"
        "Use only facts from the aggregate JSON. Never invent markets/prices/volumes/movement.\n"
        "Render probabilities as percentages (0.42 -> 42%).\n"
        "For top_markets: up to 10 items, format: question - outcome prob% (vol).\n"
        "Use one line per market, showing the dominant outcome only.\n"
        "For top_movers: up to 3 items, format: "
        "question - outcome from% -> to% (delta +/-x.x pts).\n"
        'If there are no movers, return exactly one item: ["No movers available."] '
        "for en, and [\"Движений не обнаружено.\"] for ru.\n"
        "insight must be a 1-3 sentence analyst comment.\n"
        "Schema:\n"
        "- lang=en|ru -> "
        "{headline: string, top_markets: string[], top_movers: string[], insight: string}\n"
        "- lang=both -> {en: {headline, top_markets, top_movers, insight}, "
        "ru: {headline, top_markets, top_movers, insight}}\n\n"
        f"{json.dumps(summary, ensure_ascii=False)}"
    )


def _validate_payload(parsed: Any, lang: Lang) -> bool:
    if not isinstance(parsed, dict):
        return False
    if lang == "both":
        en_payload = parsed.get("en")
        ru_payload = parsed.get("ru")
        return _validate_block(en_payload) and _validate_block(ru_payload, ru_strict=True)
    return _validate_block(parsed, ru_strict=lang == "ru")


def _validate_block(payload: Any, *, ru_strict: bool = False) -> bool:
    if not isinstance(payload, dict):
        return False
    keys = ("headline", "top_markets", "top_movers", "insight")
    if any(key not in payload for key in keys):
        return False
    if not isinstance(payload["headline"], str) or not isinstance(payload["insight"], str):
        return False
    if not isinstance(payload["top_markets"], list) or not isinstance(payload["top_movers"], list):
        return False
    if any(not isinstance(item, str) for item in payload["top_markets"] + payload["top_movers"]):
        return False
    if len(payload["top_markets"]) > 10 or len(payload["top_movers"]) > 3:
        return False
    if ru_strict:
        texts = [
            payload["headline"],
            payload["insight"],
            *payload["top_markets"],
            *payload["top_movers"],
        ]
        if any(_contains_ru_forbidden_label(text) for text in texts):
            return False
    return True


def _contains_ru_forbidden_label(text: str) -> bool:
    forbidden = ("top markets", "top movers", "markets in", "market watch")
    normalized = text.lower()
    return any(label in normalized for label in forbidden)


def _console_text_from_payload(
    payload: dict[str, Any],
    *,
    window: str,
    market_count: int,
    lang: Lang,
) -> str:
    if lang == "both":
        en_text = _console_text_for_lang(
            payload.get("en", {}),
            window=window,
            market_count=market_count,
            lang="en",
        )
        ru_text = _console_text_for_lang(
            payload.get("ru", {}),
            window=window,
            market_count=market_count,
            lang="ru",
        )
        return f"{en_text}\n\n{ru_text}"
    return _console_text_for_lang(payload, window=window, market_count=market_count, lang=lang)


def _console_text_for_lang(
    payload: dict[str, Any],
    *,
    window: str,
    market_count: int,
    lang: Literal["en", "ru"],
) -> str:
    if lang == "ru":
        section = "## Русский"
        count_line = f"- **{market_count} рынков за {window}**"
        markets_label = "**Топ рынков**"
        movers_label = "**Топ движений**"
        insight_label = "**Комментарий**"
    else:
        section = "## English"
        count_line = f"- **{market_count} markets in {window}**"
        markets_label = "**Top markets**"
        movers_label = "**Top movers**"
        insight_label = "**Insight**"

    lines = [section, count_line, "", markets_label]
    for item in payload.get("top_markets", []):
        lines.append(f"- {item}")
    lines.extend(["", movers_label])
    for item in payload.get("top_movers", []):
        lines.append(f"- {item}")
    lines.extend(["", insight_label, str(payload.get("insight", "-"))])
    return "\n".join(lines)


def _build_fallback_payload(summary: dict[str, Any], lang: Lang) -> dict[str, Any]:
    window = str(summary.get("window", "all"))
    market_count = int(summary.get("market_count", 0))
    markets = summary.get("markets", []) if isinstance(summary.get("markets"), list) else []
    movers = summary.get("top_movers", []) if isinstance(summary.get("top_movers"), list) else []
    insight = str(summary.get("text") or "Deterministic fallback summary.")

    if lang == "both":
        return {
            "en": _build_fallback_block(markets, movers, market_count, window, "en", insight),
            "ru": _build_fallback_block(markets, movers, market_count, window, "ru", insight),
        }
    return _build_fallback_block(markets, movers, market_count, window, lang, insight)


def _build_fallback_block(
    markets: list[Any],
    movers: list[Any],
    market_count: int,
    window: str,
    lang: Literal["en", "ru"],
    insight: str,
) -> dict[str, Any]:
    top_markets = [
        _format_market_line(item, lang) for item in markets[:10] if isinstance(item, dict)
    ]
    top_movers = [
        _format_mover_line(item, lang) for item in movers[:3] if isinstance(item, dict)
    ]

    if not top_movers:
        top_movers = ["No movers available."] if lang == "en" else ["Движений не обнаружено."]

    if lang == "en":
        headline = f"{market_count} markets in {window}"
    else:
        headline = f"{market_count} рынков за {window}"
    return {
        "headline": headline,
        "top_markets": top_markets,
        "top_movers": top_movers,
        "insight": insight,
    }


def _format_market_line(item: dict[str, Any], lang: Literal["en", "ru"]) -> str:
    question = str(item.get("question", "Unknown market"))
    outcome = str(item.get("outcome", "?"))
    price = _pct(item.get("price"))
    volume = item.get("volume")
    yes_no = {"yes": "Да", "no": "Нет"}
    if lang == "ru":
        outcome = yes_no.get(outcome.lower(), outcome)
        return f"{question} - {outcome} {price}% ({_fmt_volume(volume)} объём)"
    return f"{question} - {outcome} {price}% ({_fmt_volume(volume)} vol)"


def _format_mover_line(item: dict[str, Any], lang: Literal["en", "ru"]) -> str:
    question = str(item.get("question", "Unknown market"))
    outcome = str(item.get("outcome", "?"))
    yes_no = {"yes": "Да", "no": "Нет"}
    if lang == "ru":
        outcome = yes_no.get(outcome.lower(), outcome)
        return (
            f"{question} - {outcome} с {_pct(item.get('from_price'))}% -> "
            f"{_pct(item.get('to_price'))}% ({_fmt_delta(item.get('delta'))} п.п.)"
        )
    return (
        f"{question} - {outcome} from {_pct(item.get('from_price'))}% -> "
        f"{_pct(item.get('to_price'))}% ({_fmt_delta(item.get('delta'))} pts)"
    )


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "0"


def _fmt_volume(value: Any) -> str:
    try:
        return f"{float(value):.0f}"
    except (TypeError, ValueError):
        return "0"


def _fmt_delta(value: Any) -> str:
    try:
        delta = float(value) * 100
    except (TypeError, ValueError):
        return "+0.0"
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.1f}"


def _language_instruction(lang: Lang) -> str:
    if lang == "both":
        return (
            "Language mode is both.\n"
            "Provide two blocks in JSON keys en and ru.\n"
            "EN block must be fully English.\n"
            "RU block must be fully Russian.\n"
            "Do not mix labels across languages."
        )
    if lang == "ru":
        return (
            "Language mode is ru.\n"
            "All labels, headings, and bullet lines must be Russian.\n"
            "Translate questions naturally to Russian, keeping proper nouns unchanged.\n"
            "Do not output English labels."
        )
    return (
        "Language mode is en.\n"
        "All labels, headings, and bullet lines must be English.\n"
        "Do not output Russian labels."
    )


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
