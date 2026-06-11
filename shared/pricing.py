from __future__ import annotations

from shared.config import PRICING


def cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    in_p, out_p = PRICING.get(model_id, (0.0, 0.0))
    return (prompt_tokens * in_p + completion_tokens * out_p) / 1_000_000
