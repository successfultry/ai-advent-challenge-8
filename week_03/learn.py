from __future__ import annotations

import json

from openai import OpenAI

from week_03.memory import ProfileStore

ONBOARD_QUESTIONS: list[tuple[str, str]] = [
    ("Primary language (e.g. Python, Go, Rust):", "language"),
    ("Preferred stack / frameworks:", "stack"),
    ("Answer style (terse / detailed / with examples):", "style"),
    ("Format preference (code blocks, comments, etc.):", "format"),
    ("Hard constraints (stdlib only, no external libs, etc.):", "constraints"),
    ("Forbidden (never do this):", "forbidden"),
]

_EXTRACT_SYSTEM = (
    "You extract STABLE, DURABLE user coding preferences from a single user message.\n"
    "You will receive the user's current profile and their latest message.\n"
    "Return ONLY valid JSON: {\"updates\": {\"key\": \"value\"}} or {\"updates\": {}}.\n"
    "Keys are one of: language, stack, style, format, constraints, forbidden.\n\n"
    "Rules:\n"
    "- Only include keys that are explicitly stated as permanent preferences.\n"
    "- Never include one-off task details, questions, or greetings.\n"
    "- If a value already matches the current profile, do not include it.\n"
    "- If the user changes language, also reset stack to empty string so stale "
    "stack info does not conflict with the new language.\n"
    "- If the user sets a forbidden rule, use the exact wording they used.\n"
    "- Prefer concise values (e.g. 'Go' not 'the Go programming language')."
)


def run_onboarding(store: ProfileStore) -> None:
    profile = store.load()
    if profile.data:
        return
    print("\nFirst-run onboarding — answer or press Enter to skip.\n")
    for prompt, key in ONBOARD_QUESTIONS:
        ans = input(f"{prompt} ").strip()
        if ans:
            store.upsert(key, ans)
    print("Onboarding done. Profile saved.\n")


def extract_preferences(
    user_msg: str,
    current: dict[str, str],
    client: OpenAI,
    model_id: str,
) -> dict[str, str]:
    try:
        messages = [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Current profile:\n{json.dumps(current, ensure_ascii=False)}\n\n"
                    f"User message:\n{user_msg}"
                ),
            },
        ]
        resp = client.chat.completions.create(
            model=model_id,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=128,
            temperature=0,
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        updates = data.get("updates", {})
        if not isinstance(updates, dict):
            return {}
        return {
            k: str(v)
            for k, v in updates.items()
            if isinstance(k, str) and v and str(v) != current.get(k, "")
        }
    except Exception:
        return {}
