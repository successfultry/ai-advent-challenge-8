from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from week_05.chat.state import TaskState


@dataclass(frozen=True)
class SourceRef:
    chunk_id: str
    source: str
    section: str
    score: float
    label: str | None = None
    used: bool = False


@dataclass(frozen=True)
class ChatTurn:
    role: str
    text: str
    sources: list[SourceRef] = field(default_factory=list)
    grounded: bool = False
    fallback_reason: str | None = None
    rewritten_query: str | None = None


@dataclass(frozen=True)
class ChatSession:
    session_id: str
    created_at: str
    updated_at: str
    task_state: TaskState = field(default_factory=TaskState)
    turns: list[ChatTurn] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _session_id() -> str:
    return f"chat-{datetime.now(tz=UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"


def new_session(session_id: str | None = None) -> ChatSession:
    now = _now_iso()
    return ChatSession(
        session_id=session_id or _session_id(),
        created_at=now,
        updated_at=now,
        task_state=TaskState(),
        turns=[],
    )


def append_turn(session: ChatSession, turn: ChatTurn) -> ChatSession:
    return ChatSession(
        session_id=session.session_id,
        created_at=session.created_at,
        updated_at=_now_iso(),
        task_state=session.task_state,
        turns=[*session.turns, turn],
    )


def set_task_state(session: ChatSession, task_state: TaskState) -> ChatSession:
    return ChatSession(
        session_id=session.session_id,
        created_at=session.created_at,
        updated_at=_now_iso(),
        task_state=task_state,
        turns=session.turns,
    )


def load_session(path: Path) -> ChatSession:
    payload = json.loads(path.read_text(encoding="utf-8"))
    task_state_raw = payload.get("task_state", {})
    task_state = TaskState(
        goal=task_state_raw.get("goal"),
        constraints=list(task_state_raw.get("constraints", [])),
        user_clarifications=list(task_state_raw.get("user_clarifications", [])),
        fixed_terms=dict(task_state_raw.get("fixed_terms", {})),
    )
    turns: list[ChatTurn] = []
    for row in payload.get("turns", []):
        sources = [
            SourceRef(
                chunk_id=str(item.get("chunk_id", "")),
                source=str(item.get("source", "")),
                section=str(item.get("section", "")),
                score=float(item.get("score", 0.0)),
                label=item.get("label"),
                used=bool(item.get("used", False)),
            )
            for item in row.get("sources", [])
        ]
        turns.append(
            ChatTurn(
                role=str(row.get("role", "user")),
                text=str(row.get("text", "")),
                sources=sources,
                grounded=bool(row.get("grounded", False)),
                fallback_reason=row.get("fallback_reason"),
                rewritten_query=row.get("rewritten_query"),
            )
        )
    return ChatSession(
        session_id=str(payload["session_id"]),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
        task_state=task_state,
        turns=turns,
    )


def save_session(path: Path, session: ChatSession) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(session), ensure_ascii=False, indent=2), encoding="utf-8")
