from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from week_03.memory import TaskContext


class TaskState(StrEnum):
    PLANNING = "PLANNING"
    EXECUTION = "EXECUTION"
    VALIDATION = "VALIDATION"
    DONE = "DONE"


# Forward progress + pragmatic rollbacks (found a bug in VALIDATION -> back to EXECUTION,
# plan turned out incomplete in EXECUTION -> back to PLANNING).
ALLOWED: dict[TaskState, set[TaskState]] = {
    TaskState.PLANNING: {TaskState.EXECUTION},
    TaskState.EXECUTION: {TaskState.VALIDATION, TaskState.PLANNING},
    TaskState.VALIDATION: {TaskState.DONE, TaskState.EXECUTION, TaskState.PLANNING},
    TaskState.DONE: set(),
}

_NEXT: dict[TaskState, TaskState] = {
    TaskState.PLANNING: TaskState.EXECUTION,
    TaskState.EXECUTION: TaskState.VALIDATION,
    TaskState.VALIDATION: TaskState.DONE,
}


def next_stage(current: str) -> TaskState | None:
    try:
        cur = TaskState(current.upper())
    except ValueError:
        return None
    return _NEXT.get(cur)


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


def _has_approved_plan(task: TaskContext) -> bool:
    return bool(task.plan.strip())


def _has_execution_output(task: TaskContext) -> bool:
    return any(note.startswith("[execution]") for note in task.notes)


def _validation_passed(task: TaskContext) -> bool:
    return task.validation.strip().upper().startswith("STATUS=PASS")


def validate_prerequisites(
    task: TaskContext, target: str | TaskState
) -> TransitionOk | TransitionError:
    try:
        tgt = target if isinstance(target, TaskState) else TaskState(target.upper())
    except ValueError:
        valid = ", ".join(s.value for s in TaskState)
        return TransitionError(f"Unknown state {target!r}. Valid: {valid}")

    if tgt == TaskState.EXECUTION and not _has_approved_plan(task):
        return TransitionError("Cannot enter EXECUTION: plan is missing or not approved")
    if tgt == TaskState.VALIDATION and not _has_execution_output(task):
        return TransitionError("Cannot enter VALIDATION: execution result is missing")
    if tgt == TaskState.DONE and not _validation_passed(task):
        return TransitionError("Cannot enter DONE: validation did not PASS")
    return TransitionOk(new_state=tgt)
