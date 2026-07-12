from __future__ import annotations

from typing import NamedTuple


class Provider(NamedTuple):
    base_url: str
    model_id: str
    api_key_env: str | None


PROVIDERS: dict[str, Provider] = {
    "DeepSeek V3": Provider("https://api.deepseek.com", "deepseek-chat", "DEEPSEEK_API_KEY"),
    "DeepSeek R1": Provider("https://api.deepseek.com", "deepseek-reasoner", "DEEPSEEK_API_KEY"),
    "GPT-4o mini": Provider("https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY"),
    "GPT-4o": Provider("https://api.openai.com/v1", "gpt-4o", "OPENAI_API_KEY"),
    "Llama 8B (Groq)": Provider(
        "https://api.groq.com/openai/v1", "llama-3.1-8b-instant", "GROQ_API_KEY"
    ),
    "Llama 70B (Groq)": Provider(
        "https://api.groq.com/openai/v1",
        "llama-3.3-70b-versatile",
        "GROQ_API_KEY",
    ),
    "Qwen2.5 3B (Ollama, local)": Provider(
        "http://localhost:11434/v1",
        "qwen2.5:3b",
        None,
    ),
    "Qwen2.5 Coder 3B (Ollama, local)": Provider(
        "http://localhost:11434/v1",
        "qwen2.5-coder:3b",
        None,
    ),
    "Qwen2.5 Coder 7B (Ollama, local)": Provider(
        "http://localhost:11434/v1",
        "qwen2.5-coder:7b",
        None,
    ),
}

# (tier label, provider name) — provider name must match a key in PROVIDERS
BENCH_TIERS: list[tuple[str, str]] = [
    ("weak   (~8B)", "Llama 8B (Groq)"),
    ("medium (~70B)", "Llama 70B (Groq)"),
    ("strong (frontier)", "GPT-4o"),
]

# USD per 1 000 000 tokens: (input, output)
# Sources: platform.openai.com/docs/pricing, groq.com/pricing, api-docs.deepseek.com
PRICING: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
}
