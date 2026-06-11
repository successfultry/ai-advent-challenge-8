from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.pricing import cost


@dataclass
class TokenStats:
    prompt_tokens: int = field(default=0)
    completion_tokens: int = field(default=0)
    cost: float = field(default=0.0)

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, usage: Any, model_id: str) -> None:
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        self.cost += cost(model_id, usage.prompt_tokens, usage.completion_tokens)
