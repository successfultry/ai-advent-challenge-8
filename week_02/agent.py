from __future__ import annotations

from collections.abc import Iterator

from shared.client import get_client, stream_response
from week_02.memory import Msg, SessionMemory


class Agent:
    def __init__(
        self,
        provider_name: str,
        memory: SessionMemory,
        system_prompt: str | None = None,
    ) -> None:
        self.client, self.model_id = get_client(provider_name)
        self.provider_name = provider_name
        self.memory = memory
        self.system_prompt = system_prompt

    def _build_messages(self) -> list[Msg]:
        msgs: list[Msg] = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        msgs.extend(self.memory.history())
        return msgs

    def ask_stream(self, user_input: str) -> Iterator[str]:
        self.memory.add("user", user_input)
        messages = self._build_messages()

        chunks: list[str] = []
        for piece in stream_response(self.client, self.model_id, messages):
            if isinstance(piece, dict):
                continue
            chunks.append(piece)
            yield piece

        self.memory.add("assistant", "".join(chunks))

    def reset(self) -> None:
        self.memory.clear()
