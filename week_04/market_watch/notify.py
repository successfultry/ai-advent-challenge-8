import os
from html import escape
from typing import Any, Literal

import httpx

Lang = Literal["en", "ru", "both"]
_TELEGRAM_CHUNK_SIZE = 3000


def _chunks(text: str, size: int = _TELEGRAM_CHUNK_SIZE) -> list[str]:
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


def _render_single(
    payload: dict[str, Any],
    *,
    window: str,
    market_count: int,
    lang: Literal["en", "ru"],
) -> str:
    if lang == "ru":
        header = "📈 <b>Market Watch</b>"
        meta = f"🕒 <b>Окно:</b> {escape(window)}   🧮 <b>Рынков:</b> {market_count}"
        top_markets_label = "🔥 <b>Топ рынков</b>"
        top_movers_label = "📊 <b>Топ движений</b>"
        insight_label = "🧠 <b>Комментарий</b>"
    else:
        header = "📈 <b>Market Watch</b>"
        meta = f"🕒 <b>Window:</b> {escape(window)}   🧮 <b>Markets:</b> {market_count}"
        top_markets_label = "🔥 <b>Top markets</b>"
        top_movers_label = "📊 <b>Top movers</b>"
        insight_label = "🧠 <b>Insight</b>"

    top_markets = payload.get("top_markets", [])
    top_movers = payload.get("top_movers", [])
    insight = str(payload.get("insight", "")).strip()
    headline = str(payload.get("headline", "")).strip()

    lines = [header, meta]
    if headline:
        lines.extend(["", f"<b>{escape(headline)}</b>"])

    lines.extend(["", top_markets_label])
    for index, item in enumerate(top_markets, start=1):
        lines.append(f"{index}) {escape(str(item))}")

    lines.extend(["", top_movers_label])
    for item in top_movers:
        lines.append(f"- {escape(str(item))}")

    lines.extend(["", insight_label, escape(insight or "-")])
    return "\n".join(lines)


def render_telegram_message(
    payload: dict[str, Any],
    *,
    window: str,
    market_count: int,
    lang: Lang,
) -> str:
    if lang == "both":
        en_payload = payload.get("en", {})
        ru_payload = payload.get("ru", {})
        en_text = _render_single(en_payload, window=window, market_count=market_count, lang="en")
        ru_text = _render_single(ru_payload, window=window, market_count=market_count, lang="ru")
        return f"{en_text}\n\n———\n\n{ru_text}"
    return _render_single(payload, window=window, market_count=market_count, lang=lang)


async def _send_chunks(
    *,
    token: str,
    chat_id: str,
    text: str,
    parse_mode: str | None = None,
) -> str | None:
    chunks = _chunks(text)
    if not chunks:
        return "empty message"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                payload: dict[str, Any] = {
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": True,
                }
                if parse_mode is not None:
                    payload["parse_mode"] = parse_mode
                response = await client.post(url, json=payload)
                response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return f"HTTP {exc.response.status_code}"
    except httpx.HTTPError as exc:
        return str(exc)
    return None


async def send_telegram_summary(text: str) -> str | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return None
    return await _send_chunks(token=token, chat_id=chat_id, text=text)


async def send_telegram_message(
    payload: dict[str, Any],
    *,
    window: str,
    market_count: int,
    lang: Lang,
) -> str | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return None

    if lang == "both":
        en_payload = payload.get("en", {})
        ru_payload = payload.get("ru", {})
        en_text = _render_single(en_payload, window=window, market_count=market_count, lang="en")
        ru_text = _render_single(ru_payload, window=window, market_count=market_count, lang="ru")

        error = await _send_chunks(token=token, chat_id=chat_id, text=en_text, parse_mode="HTML")
        if error is not None:
            return error
        return await _send_chunks(token=token, chat_id=chat_id, text=ru_text, parse_mode="HTML")

    message = render_telegram_message(payload, window=window, market_count=market_count, lang=lang)
    return await _send_chunks(token=token, chat_id=chat_id, text=message, parse_mode="HTML")
