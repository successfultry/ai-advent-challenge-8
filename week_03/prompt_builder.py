from __future__ import annotations

from week_03.memory import Profile, TaskContext
from week_03.state import TaskState

_BASE = (
    "You are a senior pair-programmer. Reply in the user's language.\n"
    "The User Profile below is a set of HARD CONSTRAINTS, not background info. "
    "Always write real code in the profile's language/stack. Obey style and testing. "
    "Treat the Forbidden section as strict prohibitions. If a request conflicts with the "
    "profile, say so instead of silently violating it."
)


def build_system(profile: Profile, task: TaskContext | None) -> str:
    parts: list[str] = [_BASE]

    data = dict(profile.data)
    forbidden = data.pop("forbidden", None)
    style = data.pop("style", None)
    fmt = data.pop("format", None)
    constraints = data.pop("constraints", None)

    if style:
        parts.append(f"## Style\n  {style}")
    if fmt:
        parts.append(f"## Format\n  {fmt}")
    if constraints:
        parts.append(f"## Constraints\n  {constraints}")
    if data:
        lines = "\n".join(f"  {k}: {v}" for k, v in data.items())
        parts.append(f"## User Profile\n{lines}")
    if forbidden:
        parts.append(f"## Forbidden (never do)\n  {forbidden}")

    if task is not None and (task.plan or task.decisions or task.notes or task.validation):
        rows = [
            f"  name: {task.name}",
            f"  state: {task.state}",
        ]
        if task.plan:
            rows.append(f"  plan: {task.plan}")
        for d in task.decisions:
            rows.append(f"  decision: {d}")
        for n in task.notes:
            rows.append(f"  note: {n}")
        if task.validation:
            rows.append(f"  validation: {task.validation}")
        parts.append("## Active Task\n" + "\n".join(rows))

    return "\n\n".join(parts)


# Shared rules appended to every stage prompt. Keep terse — these are hard rules.
_STAGE_RULES = (
    "Rules: reply with ONLY one JSON object, no prose, no markdown fences. "
    "Use EXACTLY the keys specified, no extra keys. Arrays must be non-empty. "
    "Obey the User Profile (style/constraints/forbidden) above as hard constraints."
)

STAGE_PROMPTS: dict[TaskState, str] = {
    TaskState.PLANNING: (
        "You are a PLANNING agent. Break the task into 3-7 concrete, actionable steps "
        "(each a single verifiable action, in the profile's stack). Do NOT write the "
        "implementation yet.\n"
        "Emit JSON:\n"
        '{"plan": ["step 1", "step 2", ...], '
        '"current_step": "<the first step to do>", '
        '"expected_action": "<what you need from the user before execution>"}\n'
        f"{_STAGE_RULES}"
    ),
    TaskState.EXECUTION: (
        "You are an EXECUTION agent. Implement EVERY step from ## Prior Plan. You have no "
        "tools, so put the ACTUAL code inline in `result` (complete, runnable, profile's "
        "stack). `artifacts` lists the file paths this code would be saved to.\n"
        "Emit JSON:\n"
        '{"result": "<the full code / concrete output>", '
        '"artifacts": ["path/to/file", ...], '
        '"current_step": "<what was just implemented>", '
        '"expected_action": "await validation"}\n'
        f"{_STAGE_RULES}"
    ),
    TaskState.VALIDATION: (
        "You are a VALIDATION agent. Check the execution result (see ## Task Context notes) "
        "against the plan AND the profile constraints/forbidden. Be strict: missing steps, "
        "forbidden tech, or non-runnable code => FAIL.\n"
        "Emit JSON:\n"
        '{"status": "PASS" or "FAIL", '
        '"issues": ["concrete issue", ...], '
        '"rollback_to": "none" (PASS) | "execution" (code wrong) | "planning" (plan wrong), '
        '"current_step": "validation", '
        '"expected_action": "proceed to done (PASS) or rollback to execution/planning (FAIL)"}\n'
        'If everything is correct, status=PASS, issues=["none"], rollback_to="none".\n'
        f"{_STAGE_RULES}"
    ),
    TaskState.DONE: (
        "You are a DONE agent. The task passed validation. Summarize what was accomplished "
        "and how it was validated.\n"
        "Emit JSON:\n"
        '{"summary": "<what was built and how it was validated>", '
        '"current_step": "done", '
        '"expected_action": "none"}\n'
        f"{_STAGE_RULES}"
    ),
}


def _profile_sections(profile: Profile) -> list[str]:
    parts: list[str] = []
    data = dict(profile.data)
    forbidden = data.pop("forbidden", None)
    style = data.pop("style", None)
    fmt = data.pop("format", None)
    constraints = data.pop("constraints", None)
    if style:
        parts.append(f"## Style\n  {style}")
    if fmt:
        parts.append(f"## Format\n  {fmt}")
    if constraints:
        parts.append(f"## Constraints\n  {constraints}")
    if data:
        lines = "\n".join(f"  {k}: {v}" for k, v in data.items())
        parts.append(f"## User Profile\n{lines}")
    if forbidden:
        parts.append(f"## Forbidden (never do)\n  {forbidden}")
    return parts


def build_stage_system(profile: Profile, task: TaskContext, stage: TaskState) -> str:
    parts: list[str] = [_BASE]
    parts.extend(_profile_sections(profile))

    rows = [f"  name: {task.name}", f"  stage: {stage.value}"]
    if task.plan:
        rows.append(f"  plan: {task.plan}")
    for d in task.decisions:
        rows.append(f"  decision: {d}")
    for n in task.notes:
        rows.append(f"  note: {n}")
    if task.validation:
        rows.append(f"  validation: {task.validation}")
    if task.last_stage_output:
        rows.append(f"  last_stage_output: {task.last_stage_output}")
    if rows:
        label = "Prior Plan" if stage == TaskState.EXECUTION else "Task Context"
        parts.append(f"## {label}\n" + "\n".join(rows))

    parts.append(STAGE_PROMPTS[stage])
    return "\n\n".join(parts)
