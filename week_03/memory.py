from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

Msg = dict[str, str]
DATA_DIR = Path("data")


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "task"


@dataclass
class Profile:
    version: int = 1
    data: dict[str, str] = field(default_factory=dict)


@dataclass
class TaskContext:
    version: int = 1
    task_id: str = ""
    name: str = ""
    state: str = "PLANNING"
    plan: str = ""
    decisions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    validation: str = ""
    current_step: str = ""
    expected_action: str = ""
    last_stage_output: str = ""
    updated_at: str = ""


def _parse_profile_md(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_key is not None:
                data[current_key] = "\n".join(current_lines).strip()
            current_key = line[3:].strip()
            current_lines = []
        elif current_key is not None and not line.startswith("# "):
            current_lines.append(line)
    if current_key is not None:
        data[current_key] = "\n".join(current_lines).strip()
    return data


def _render_profile_md(user: str, data: dict[str, str]) -> str:
    lines: list[str] = [f"# Profile: {user}", ""]
    for key, value in data.items():
        lines.append(f"## {key}")
        lines.append(value)
        lines.append("")
    return "\n".join(lines)


class ProfileStore:
    def __init__(self, user: str) -> None:
        self._user = user
        self._path = DATA_DIR / "long_term" / f"{user}.md"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Profile:
        if not self._path.exists():
            return Profile()
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return Profile()
        return Profile(data=_parse_profile_md(text))

    def save(self, profile: Profile) -> None:
        _atomic_write_text(self._path, _render_profile_md(self._user, profile.data))

    def upsert(self, key: str, value: str) -> Profile:
        p = self.load()
        p.data[key] = value
        self.save(p)
        return p


class WorkingStore:
    def __init__(self, user: str, task_id: str) -> None:
        self._path = DATA_DIR / "working" / f"{user}_{task_id}.json"
        self._task_id = task_id

    def exists(self) -> bool:
        return self._path.exists()

    def load(self) -> TaskContext:
        raw = _read_json(self._path, {})
        if not isinstance(raw, dict):
            raw = {}
        return TaskContext(
            version=int(raw.get("version", 1)),
            task_id=raw.get("task_id", self._task_id),
            name=raw.get("name", self._task_id),
            state=raw.get("state", "PLANNING"),
            plan=raw.get("plan", ""),
            decisions=list(raw.get("decisions", [])),
            notes=list(raw.get("notes", [])),
            validation=raw.get("validation", ""),
            current_step=raw.get("current_step", ""),
            expected_action=raw.get("expected_action", ""),
            last_stage_output=raw.get("last_stage_output", ""),
            updated_at=raw.get("updated_at", ""),
        )

    def save(self, ctx: TaskContext) -> None:
        ctx.updated_at = datetime.now(tz=UTC).isoformat()
        _atomic_write(
            self._path,
            {
                "version": ctx.version,
                "task_id": ctx.task_id,
                "name": ctx.name,
                "state": ctx.state,
                "plan": ctx.plan,
                "decisions": ctx.decisions,
                "notes": ctx.notes,
                "validation": ctx.validation,
                "current_step": ctx.current_step,
                "expected_action": ctx.expected_action,
                "last_stage_output": ctx.last_stage_output,
                "updated_at": ctx.updated_at,
            },
        )


class ShortTermStore:
    def __init__(self, user: str, chat: str, *, fresh: bool = False) -> None:
        self._path = DATA_DIR / "short_term" / f"{user}_{chat}.json"
        self._messages: list[Msg] = []
        if not fresh:
            self._load()

    def _load(self) -> None:
        raw = _read_json(self._path, {})
        if not isinstance(raw, dict):
            raw = {}
        msgs = raw.get("messages", [])
        if not isinstance(msgs, list):
            msgs = []
        self._messages = [m for m in msgs if isinstance(m, dict) and "role" in m and "content" in m]
        # drop dangling user turn from an interrupted session
        if self._messages and self._messages[-1].get("role") == "user":
            self._messages.pop()

    def _save(self) -> None:
        _atomic_write(self._path, {"version": 1, "messages": self._messages})

    def add(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})
        self._save()

    def pop_last(self) -> None:
        if self._messages:
            self._messages.pop()
            self._save()

    def clear(self) -> None:
        self._messages.clear()
        self._save()

    def messages(self) -> list[Msg]:
        return list(self._messages)


def load_active_task_id(user: str) -> str | None:
    path = DATA_DIR / "active_task" / f"{user}.json"
    raw = _read_json(path, {})
    if not isinstance(raw, dict):
        return None
    tid = raw.get("active_task")
    return tid if isinstance(tid, str) else None


def set_active_task_id(user: str, task_id: str | None) -> None:
    path = DATA_DIR / "active_task" / f"{user}.json"
    _atomic_write(path, {"active_task": task_id})
