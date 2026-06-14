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


class FileMemory:
    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.messages: list[Msg] = []
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
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


class BranchingMemory:
    """
    Adapter over per-branch FileMemory instances. Implements Memory Protocol by
    delegating to the active branch. Branch-specific methods are NOT on the Protocol —
    CLI accesses them via isinstance(memory, BranchingMemory).
    """

    def __init__(self, base_path: Path, pointer_path: Path) -> None:
        self._base_path = base_path
        self._pointer_path = pointer_path
        self._branches: dict[str, FileMemory] = {}
        self._active: str = "main"
        self._load_pointer()
        # ensure main branch always exists, backed by the canonical history file
        if "main" not in self._branches:
            self._branches["main"] = FileMemory(base_path)

    def _load_pointer(self) -> None:
        if not self._pointer_path.exists():
            return
        try:
            data = json.loads(self._pointer_path.read_text(encoding="utf-8"))
            self._active = data.get("active", "main")
            for name in data.get("branches", []):
                if name == "main":
                    self._branches["main"] = FileMemory(self._base_path)
                else:
                    path = self._branch_path(name)
                    self._branches[name] = FileMemory(path)
        except Exception:
            self._active = "main"

    def _save_pointer(self) -> None:
        self._pointer_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"active": self._active, "branches": list(self._branches.keys())}
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._pointer_path.parent,
            delete=False,
            suffix=".tmp",
        )
        try:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp_path = Path(tmp.name)
        finally:
            tmp.close()
        tmp_path.replace(self._pointer_path)

    def _branch_path(self, name: str) -> Path:
        return self._base_path.with_name(
            self._base_path.stem + "__" + name + self._base_path.suffix
        )

    @property
    def active(self) -> str:
        return self._active

    def _current(self) -> FileMemory:
        return self._branches[self._active]

    # Memory Protocol
    def add(self, role: str, content: str) -> None:
        self._current().add(role, content)

    def history(self) -> list[Msg]:
        return self._current().history()

    def pop_last(self) -> None:
        self._current().pop_last()

    def clear(self) -> None:
        self._current().clear()

    # Branch-only capability (accessed via isinstance guard in CLI)
    def create_branch(self, name: str) -> None:
        if name in self._branches:
            raise ValueError(f"Branch '{name}' already exists")
        path = self._branch_path(name)
        new_mem = FileMemory(path)
        # fork: copy active branch messages into the new branch via public API
        for msg in self._current().history():
            new_mem.add(msg["role"], msg["content"])
        self._branches[name] = new_mem
        self._active = name
        self._save_pointer()

    def switch_branch(self, name: str) -> None:
        if name not in self._branches:
            raise ValueError(f"Branch '{name}' does not exist")
        self._active = name
        self._save_pointer()

    def list_branches(self) -> list[str]:
        return list(self._branches.keys())
