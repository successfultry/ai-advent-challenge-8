from __future__ import annotations

from week_03.memory import Profile, TaskContext, load_invariants_text
from week_03.state import TaskState

_BASE = (
    "You are a senior pair-programmer. Reply in the user's language.\n"
    "Priority order: Invariants > User Profile > Active Task > user request. "
    "If an Invariants section is present, treat it as non-negotiable project rules. "
    "Treat the User Profile as hard user preferences and constraints. "
    "If a request conflicts with Invariants or User Profile, refuse briefly and cite the rule."
)


def build_system(profile: Profile, task: TaskContext | None) -> str:
    parts: list[str] = [_BASE]
    parts.extend(_render_profile_sections(profile))

    inv = load_invariants_text()
    if inv:
        parts.append(f"## Invariants\n{inv}")

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
    "Use EXACTLY the keys specified, no extra keys. Arrays must be non-empty unless "
    "the current stage schema explicitly permits an empty array. "
    "Obey the User Profile (style/constraints/forbidden) above as hard constraints."
)

STAGE_PROMPTS: dict[TaskState, str] = {
    TaskState.PLANNING: (
        "You are a PLANNING agent. First, check the task against ## Invariants. "
        "If the task violates any invariant, return status=REJECTED and explain the "
        "concrete violation in reason. Do not generate a plan.\n"
        "Otherwise, break the task into 3-7 concrete, actionable steps "
        "(each a single verifiable action, in the profile's stack). Do NOT write the "
        "implementation yet.\n"
        'ACCEPTED requires reason="none" and a non-empty plan. REJECTED requires '
        'reason to cite the violated invariant, plan=[], current_step="rejected", '
        'expected_action="revise request", and no implementation steps.\n'
        "Emit JSON:\n"
        '{"status": "ACCEPTED" | "REJECTED", '
        '"reason": "none" | "<why rejected>", '
        '"plan": ["step 1", "step 2", ...] | [], '
        '"current_step": "<the first step to do or rejected>", '
        '"expected_action": "<what you need from the user before execution or revise request>"}\n'
        f"{_STAGE_RULES}"
    ),
    TaskState.EXECUTION: (
        "You are an EXECUTION agent. Implement the ENTIRE task from ## Prior Plan in one shot. "
        "You have no tools, so put the ACTUAL, complete, runnable code inline in `result` "
        "(profile's stack). `artifacts` lists the file paths this code would be saved to.\n"
        "Emit JSON:\n"
        '{"result": "<the full code / concrete output>", '
        '"artifacts": ["path/to/file", ...], '
        '"current_step": "execution complete", '
        '"expected_action": "await validation"}\n'
        f"{_STAGE_RULES}"
    ),
    TaskState.VALIDATION: (
        "You are a VALIDATION agent. Judge the DELIVERABLE — the code in the latest "
        "[execution] note — for correctness against the task goal, the profile "
        "(style/constraints/forbidden), AND ## Invariants.\n"
        "PASS if the code correctly solves the task and obeys the profile and invariants. "
        "FAIL ONLY for real defects: wrong output, syntax errors, forbidden tech, "
        "direct contradiction of the task, or violation of any invariant. "
        "If an invariant is violated, cite that invariant in issues. Use "
        'rollback_to="execution" when the implementation violates an invariant; use '
        'rollback_to="planning" when the plan itself violates an invariant. '
        "Do NOT fail because plan steps aren't individually logged, or because a test run "
        "isn't shown — one-shot codegen has no separate test step.\n"
        'Decide status FIRST. `issues` is a flat list of concrete defects or ["none"] — never '
        "put reasoning or second-guessing there. FAIL requires rollback_to=execution|planning; "
        "PASS requires rollback_to=none.\n"
        "Emit JSON:\n"
        '{"status": "PASS" or "FAIL", '
        '"issues": ["concrete issue", ...], '
        '"rollback_to": "none" (PASS) | "execution" (code wrong) | "planning" (plan wrong), '
        '"current_step": "validation", '
        '"expected_action": "proceed to done (PASS) or rollback to execution/planning (FAIL)"}\n'
        'If correct: status=PASS, issues=["none"], rollback_to="none".\n'
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


def _render_profile_sections(profile: Profile) -> list[str]:
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
    parts.extend(_render_profile_sections(profile))

    inv = load_invariants_text()
    if inv:
        parts.append(f"## Invariants\n{inv}")

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
