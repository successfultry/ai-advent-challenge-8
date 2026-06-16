from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskState(str, Enum):
    PLANNING = "PLANNING"
    EXECUTION = "EXECUTION"
    VALIDATION = "VALIDATION"
    DONE = "DONE"


# Forward progress + pragmatic rollbacks (found a bug in VALIDATION -> back to EXECUTION,
# plan turned out incomplete in EXECUTION -> back to PLANNING).
ALLOWED: dict[TaskState, set[TaskState]] = {
    TaskState.PLANNING: {TaskState.EXECUTION},
    TaskState.EXECUTION: {TaskState.VALIDATION, TaskState.PLANNING},
    TaskState.VALIDATION: {TaskState.DONE, TaskState.EXECUTION},
    TaskState.DONE: set(),
}


@dataclass
class TransitionOk:
    new_state: TaskState


@dataclass
class TransitionError:
    message: str


def validate_transition(current: str, target: str) -> TransitionOk | TransitionError:
    try:
        cur = TaskState(current.upper())
    except ValueError:
        return TransitionError(f"Unknown current state: {current!r}")
    try:
        tgt = TaskState(target.upper())
    except ValueError:
        valid = ", ".join(s.value for s in TaskState)
        return TransitionError(f"Unknown state {target!r}. Valid: {valid}")
    if tgt in ALLOWED.get(cur, set()):
        return TransitionOk(new_state=tgt)
    allowed = ALLOWED.get(cur, set())
    next_str = ", ".join(sorted(s.value for s in allowed)) if allowed else "none (task is DONE)"
    return TransitionError(
        f"Invalid: {cur.value} → {tgt.value}. Allowed from {cur.value}: {next_str}"
    )
