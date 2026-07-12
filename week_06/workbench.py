from __future__ import annotations

import os
from dataclasses import dataclass

from shared.config import PROVIDERS
from week_06.local_client import OllamaClient, OllamaClientError

DEFAULT_MODE = "general"
MAX_HISTORY_ITEMS = 5

MODE_INSTRUCTIONS: dict[str, str] = {
    "general": (
        "Answer in the same language as the user. "
        "Be concise: at most 3 sentences unless code is explicitly requested. "
        "Do not produce step-by-step setup guides unless asked."
    ),
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
    validate_mode(mode)
    return clean_prompt


class WorkbenchService:
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def ask(self, mode: str, prompt: str) -> WorkbenchResult:
        final_prompt = build_prompt(mode, prompt)
        client = OllamaClient(provider_name=self.provider_name)

        temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
        top_p = float(os.getenv("LLM_TOP_P", "0.9"))
        max_tokens = int(os.getenv("LLM_MAX_TOKENS", "220"))

        response = client.generate(
            final_prompt,
            system=MODE_INSTRUCTIONS[mode],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
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
        return result


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
