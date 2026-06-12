from __future__ import annotations

from typing import Any

from openai import OpenAI

from shared.client import get_response
from week_02.memory import Msg


def summarize(
    client: OpenAI, model_id: str, messages: list[Msg], existing_summary: str | None
) -> tuple[str, Any]:
    rules = (
        "Keep ALL facts, names, preferences, and decisions. "
        "If something is not present, do NOT invent it. "
        "Be concise, use bullet points."
    )
    new_block = "\n".join(f"{m['role']}: {m['content']}" for m in messages)

    if existing_summary:
        full_prompt = (
            "You maintain a running summary of a conversation.\n"
            "Merge the PREVIOUS SUMMARY with the NEW MESSAGES into one updated summary.\n"
            "NEVER drop anything from the previous summary — carry every earlier fact "
            "forward, then add what is new.\n"
            f"{rules}\n\n"
            f"=== PREVIOUS SUMMARY ===\n{existing_summary}\n\n"
            f"=== NEW MESSAGES ===\n{new_block}"
        )
    else:
        full_prompt = f"Summarize the following conversation.\n{rules}\n\n{new_block}"

    summary, _, usage = get_response(client, model_id, [{"role": "user", "content": full_prompt}])
    return summary, usage
