from __future__ import annotations

PROVIDERS: dict[str, tuple[str, str, str]] = {
    "DeepSeek V3": ("https://api.deepseek.com", "deepseek-chat", "DEEPSEEK_API_KEY"),
    "DeepSeek R1": ("https://api.deepseek.com", "deepseek-reasoner", "DEEPSEEK_API_KEY"),
    "GPT-4o mini": ("https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY"),
    "GPT-4o": ("https://api.openai.com/v1", "gpt-4o", "OPENAI_API_KEY"),
}
