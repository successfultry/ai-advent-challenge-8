from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Protocol

Msg = dict[str, str]


class Memory(Protocol):
    def add(self, role: str, content: str) -> None: ...
    def history(self) -> list[Msg]: ...
    def pop_last(self) -> None: ...
    def clear(self) -> None: ...


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


class FileMemory:
    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.messages: list[Msg] = []
        self._load()

    def _load(self) -> None:
        if not self.filepath.exists():
            return

        try:
            data = json.loads(self.filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._save()
            return

        if not isinstance(data, list):
            self._save()
            return

        self.messages = [m for m in data if isinstance(m, dict) and "role" in m and "content" in m]

        if self.messages and self.messages[-1].get("role") == "user":
            self.messages.pop()

        if len(self.messages) != len(data):
            self._save()

    def _save(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.filepath.parent,
            delete=False,
            suffix=".tmp",
        ) as tmp:
            json.dump(self.messages, tmp, ensure_ascii=False, indent=2)
            tmp_path = Path(tmp.name)

        tmp_path.replace(self.filepath)

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        self._save()

    def pop_last(self) -> None:
        if self.messages:
            self.messages.pop()
            self._save()

    def clear(self) -> None:
        self.messages.clear()
        self._save()

    def history(self) -> list[Msg]:
        return list(self.messages)
