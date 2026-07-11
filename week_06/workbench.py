from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

from shared.config import PROVIDERS
from week_06.local_client import OllamaClient, OllamaClientError

DEFAULT_MODE = "general"
MAX_HISTORY_ITEMS = 5

MODE_INSTRUCTIONS: dict[str, str] = {
    "general": "Answer clearly and concisely. If code is needed, keep it minimal.",
    "explain_error": (
        "You are a senior Python backend engineer. Explain the terminal error, likely "
        "root cause, and exact fix. Keep it concise and practical."
    ),
    "generate_pytest": (
        "Generate pytest tests for the pasted Python code. Return only test code and short setup "
        "notes."
    ),
    "architecture_review": (
        "Review this backend/AWS design. Return risks, missing constraints, and practical "
        "improvements. Keep it concise."
    ),
}


@dataclass
class WorkbenchResult:
    text: str
    latency_seconds: float
    finish_reason: str
    model: str
    provider: str
    tokens_out: int | None = None
    tokens_per_sec: float | None = None
    prompt_tokens: int | None = None
    load_seconds: float | None = None


@dataclass
class HistoryItem:
    mode: str
    prompt: str
    answer_preview: str
    latency_seconds: float
    finish_reason: str
    model: str
    provider: str
    tokens_out: int | None = None
    tokens_per_sec: float | None = None


def local_providers() -> list[str]:
    return [name for name, provider in PROVIDERS.items() if provider.api_key_env is None]


def validate_mode(mode: str) -> str:
    if mode not in MODE_INSTRUCTIONS:
        raise ValueError(
            f"Unsupported mode: {mode}. Expected one of: {', '.join(MODE_INSTRUCTIONS.keys())}"
        )
    return mode


def build_prompt(mode: str, user_prompt: str) -> str:
    clean_prompt = user_prompt.strip()
    if not clean_prompt:
        raise ValueError("Prompt must not be empty")

    instruction = MODE_INSTRUCTIONS[validate_mode(mode)]
    return f"Instruction:\n{instruction}\n\nUser request:\n{clean_prompt}"


def _preview(text: str, *, max_chars: int = 140) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 1]}…"


class WorkbenchService:
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        self._history: deque[HistoryItem] = deque(maxlen=MAX_HISTORY_ITEMS)

    def ask(self, mode: str, prompt: str) -> WorkbenchResult:
        final_prompt = build_prompt(mode, prompt)
        client = OllamaClient(provider_name=self.provider_name)
        response = client.generate(final_prompt)
        result = WorkbenchResult(
            text=response.text,
            latency_seconds=response.latency_seconds,
            finish_reason=response.finish_reason,
            model=client.model_id,
            provider=client.provider_name,
            tokens_out=response.tokens_out,
            tokens_per_sec=response.tokens_per_sec,
            prompt_tokens=response.prompt_tokens,
            load_seconds=response.load_seconds,
        )
        self._history.appendleft(
            HistoryItem(
                mode=mode,
                prompt=prompt.strip(),
                answer_preview=_preview(result.text),
                latency_seconds=result.latency_seconds,
                finish_reason=result.finish_reason,
                model=result.model,
                provider=result.provider,
                tokens_out=result.tokens_out,
                tokens_per_sec=result.tokens_per_sec,
            )
        )
        return result

    def history(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in self._history]


__all__ = [
    "DEFAULT_MODE",
    "MAX_HISTORY_ITEMS",
    "MODE_INSTRUCTIONS",
    "OllamaClientError",
    "WorkbenchResult",
    "WorkbenchService",
    "build_prompt",
    "local_providers",
]
