from __future__ import annotations

Msg = dict[str, str]


class SessionMemory:
    def __init__(self) -> None:
        self.messages: list[Msg] = []

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def history(self) -> list[Msg]:
        return list(self.messages)

    def pop_last(self) -> None:
        if self.messages:
            self.messages.pop()

    def clear(self) -> None:
        self.messages.clear()
