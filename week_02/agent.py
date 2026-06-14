from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from shared.client import get_client, stream_response
from week_02.context import ContextPolicy, PolicyResult
from week_02.memory import Memory
from week_02.stats import TokenStats


class Agent:
    def __init__(
        self,
        provider_name: str,
        memory: Memory,
        policy: ContextPolicy,
        stats: TokenStats,
        system_prompt: str | None = None,
    ) -> None:
        self.client, self.model_id = get_client(provider_name)
        self.provider_name = provider_name
        self.memory = memory
        self.policy = policy
        self.stats = stats
        self.system_prompt = system_prompt
        self.last_usage: Any = None
        self.last_result: PolicyResult | None = None

    def ask_stream(self, user_input: str) -> Iterator[str]:
        self.last_usage = None
        self.last_result = None
        self.memory.add("user", user_input)
        result = self.policy.compress_if_needed(self.memory)
        if result.changed and result.usage:
            self.stats.add(result.usage, result.usage_model_id or self.model_id)
        self.last_result = result
        messages = self.policy.build_messages(self.memory, self.system_prompt)

        chunks: list[str] = []
        for piece in stream_response(self.client, self.model_id, messages):
            if isinstance(piece, dict):
                usage = piece.get("usage")
                if usage is not None:
                    self.last_usage = usage
                    self.stats.add(usage, self.model_id)
                continue
            chunks.append(piece)
            yield piece

        self.memory.add("assistant", "".join(chunks))

    def reset(self) -> None:
        self.memory.clear()
        self.policy.reset_state()
