from __future__ import annotations

PROVIDERS: dict[str, tuple[str, str, str]] = {
    "DeepSeek V3": ("https://api.deepseek.com", "deepseek-chat", "DEEPSEEK_API_KEY"),
    "DeepSeek R1": ("https://api.deepseek.com", "deepseek-reasoner", "DEEPSEEK_API_KEY"),
    "GPT-4o mini": ("https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY"),
    "GPT-4o": ("https://api.openai.com/v1", "gpt-4o", "OPENAI_API_KEY"),
    "Llama 8B (Groq)": ("https://api.groq.com/openai/v1", "llama-3.1-8b-instant", "GROQ_API_KEY"),
    "Llama 70B (Groq)": (
        "https://api.groq.com/openai/v1",
        "llama-3.3-70b-versatile",
        "GROQ_API_KEY",
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
