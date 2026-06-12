from __future__ import annotations

from typing import Any

from openai import OpenAI

from shared.client import get_response
from week_02.memory import Msg


def summarize(
    client: OpenAI, model_id: str, messages: list[Msg], existing_summary: str | None
) -> tuple[str, Any]:
    prompt = (
        "Summarize the following conversation. "
        "Keep all facts, names, preferences, decisions. "
        "If something is not in the conversation, do NOT invent it. "
        "Be concise, use bullet points."
    )
    if existing_summary:
        prompt = f"Previous summary:\n{existing_summary}\n\n{prompt}"
    content = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    full_prompt = f"{prompt}\n\n{content}"
    summary, _, usage = get_response(client, model_id, [{"role": "user", "content": full_prompt}])
    return summary, usage
