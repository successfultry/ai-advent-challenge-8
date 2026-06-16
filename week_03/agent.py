from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from shared.client import get_client, stream_response
from week_03.memory import ShortTermStore
from week_03.stats import TokenStats


class Agent:
    def __init__(
        self,
        provider_name: str,
        short_term: ShortTermStore,
        build_system: Callable[[], str],
        stats: TokenStats,
    ) -> None:
        self.provider_name = provider_name
        self.short_term = short_term
        self.build_system = build_system
        self.stats = stats
        self.client, self.model_id = get_client(provider_name)
        self.last_usage: Any = None

    def switch_provider(self, provider_name: str) -> None:
        self.provider_name = provider_name
        self.client, self.model_id = get_client(provider_name)

    def ask_stream(self, user_input: str) -> Iterator[str]:
        self.last_usage = None
        self.short_term.add("user", user_input)

        # rebuild system prompt fresh from current layer state on every call
        system = self.build_system()
        messages = [{"role": "system", "content": system}, *self.short_term.messages()]

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

        self.short_term.add("assistant", "".join(chunks))
