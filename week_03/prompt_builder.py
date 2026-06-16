from __future__ import annotations

from week_03.memory import Profile, TaskContext

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

    if data:
        lines = "\n".join(f"  {k}: {v}" for k, v in data.items())
        parts.append(f"## User Profile (hard constraints)\n{lines}")

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
