from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from shared.client import get_response
from week_02.memory import Msg

_JSON_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    m = _JSON_FENCE.match(text)
    if m:
        text = m.group(1).strip()
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("model returned non-dict JSON")
    return result


def extract(
    client: OpenAI, model_id: str, messages: list[Msg], current_facts: dict
) -> tuple[dict, Any]:
    conv_block = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    existing_block = (
        json.dumps(current_facts, ensure_ascii=False, indent=2) if current_facts else "{}"
    )
    prompt = (
        "You maintain a structured key-value fact store about the user and conversation.\n"
        "Given the CURRENT FACTS and the CONVERSATION, return an UPDATED JSON object.\n"
        "Rules:\n"
        "- Keep all existing facts unless explicitly contradicted.\n"
        "- Add new facts you can reliably extract (name, preferences, decisions, context).\n"
        "- Use short snake_case keys, concise string values.\n"
        "- Return ONLY valid JSON, no markdown fences, no explanation.\n\n"
        f"=== CURRENT FACTS ===\n{existing_block}\n\n"
        f"=== CONVERSATION ===\n{conv_block}"
    )
    msgs = [{"role": "user", "content": prompt}]
    # prefer structured JSON mode; fall back if the provider doesn't support it
    try:
        raw, _, usage = get_response(
            client, model_id, msgs, response_format={"type": "json_object"}
        )
    except Exception:
        raw, _, usage = get_response(client, model_id, msgs)
    return _parse_json(raw), usage
