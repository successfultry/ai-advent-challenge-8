from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from shared.client import get_client, stream_response
from week_02.memory import Memory, Msg
from week_02.stats import TokenStats

# 1 token ≈ 4 chars — rough heuristic for demo context limit
MAX_CONTEXT_TOKENS = 500


class Agent:
    def __init__(
        self,
        provider_name: str,
        memory: Memory,
        system_prompt: str | None = None,
    ) -> None:
        self.client, self.model_id = get_client(provider_name)
        self.provider_name = provider_name
        self.memory = memory
        self.system_prompt = system_prompt
        self.stats = TokenStats()
        self.last_usage: Any = None
        self.last_dropped: int = 0

    def _truncate(self, messages: list[Msg]) -> list[Msg]:
        msgs = list(messages)
        start = 1 if msgs and msgs[0]["role"] == "system" else 0
        char_budget = MAX_CONTEXT_TOKENS * 4
        total_chars = sum(len(m["content"]) for m in msgs)

        while total_chars > char_budget and start < len(msgs) - 1:
            total_chars -= len(msgs[start]["content"])
            msgs.pop(start)
            self.last_dropped += 1

        # strict APIs want the first non-system message to be a user turn
        if start < len(msgs) - 1 and msgs[start]["role"] == "assistant":
            msgs.pop(start)
            self.last_dropped += 1

        return msgs

    def _build_messages(self) -> list[Msg]:
        msgs: list[Msg] = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        msgs.extend(self.memory.history())
        return self._truncate(msgs)

    def ask_stream(self, user_input: str) -> Iterator[str]:
        self.last_usage = None
        self.last_dropped = 0
        self.memory.add("user", user_input)
        messages = self._build_messages()

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
        self.stats = TokenStats()
