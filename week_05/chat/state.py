from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskState:
    goal: str | None = None
    constraints: list[str] = field(default_factory=list)
    user_clarifications: list[str] = field(default_factory=list)
    fixed_terms: dict[str, str] = field(default_factory=dict)


_GOAL_PREFIXES = (
    "цель:",
    "goal:",
    "новая цель:",
    "теперь цель:",
)
_CONSTRAINT_PREFIXES = (
    "ограничение:",
    "constraint:",
    "important:",
    "важно:",
)
_CLARIFICATION_MARKERS = (
    "уточню",
    "имею в виду",
    "давай считать",
)
_TERM_PATTERNS = (
    re.compile(r"термин\s+(.+?)\s*=\s*(.+)", flags=re.IGNORECASE),
    re.compile(r"(.+?)\s+means\s+(.+)", flags=re.IGNORECASE),
)


def _extract_prefixed_value(message: str, prefixes: tuple[str, ...]) -> str | None:
    lowered = message.lower().strip()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return message[len(prefix) :].strip()
    return None


def _append_unique(items: list[str], value: str) -> list[str]:
    normalized = value.strip()
    if not normalized:
        return items
    if normalized in items:
        return items
    return [*items, normalized]


def update_task_state(state: TaskState, user_message: str) -> TaskState:
    message = user_message.strip()
    if not message:
        return state

    goal = state.goal
    constraints = list(state.constraints)
    clarifications = list(state.user_clarifications)
    fixed_terms = dict(state.fixed_terms)

    explicit_goal = _extract_prefixed_value(message, _GOAL_PREFIXES)
    if explicit_goal:
        goal = explicit_goal
    elif goal is None and len(message) >= 8:
        # First substantive message fallback.
        goal = message

    explicit_constraint = _extract_prefixed_value(message, _CONSTRAINT_PREFIXES)
    if explicit_constraint:
        constraints = _append_unique(constraints, explicit_constraint)

    lowered = message.lower()
    if any(marker in lowered for marker in _CLARIFICATION_MARKERS):
        clarifications = _append_unique(clarifications, message)

    for pattern in _TERM_PATTERNS:
        match = pattern.search(message)
        if match:
            term = match.group(1).strip()
            meaning = match.group(2).strip()
            if term and meaning:
                fixed_terms[term] = meaning

    return TaskState(
        goal=goal,
        constraints=constraints,
        user_clarifications=clarifications,
        fixed_terms=fixed_terms,
    )


def render_task_state(state: TaskState) -> str:
    parts: list[str] = []
    if state.goal:
        parts.append(f"Goal: {state.goal}")
    if state.constraints:
        parts.append("Constraints: " + "; ".join(state.constraints[:5]))
    if state.user_clarifications:
        parts.append("Clarifications: " + "; ".join(state.user_clarifications[-5:]))
    if state.fixed_terms:
        pairs = [f"{key}={value}" for key, value in list(state.fixed_terms.items())[:8]]
        parts.append("Fixed terms: " + "; ".join(pairs))
    return " | ".join(parts) if parts else "Goal: not set"
