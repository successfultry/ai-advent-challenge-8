from __future__ import annotations

from week_03.memory import Profile, TaskContext

_BASE = (
    "You are a concise assistant. Answer precisely and in the same language the user writes in."
)


def build_system(profile: Profile, task: TaskContext | None) -> str:
    parts: list[str] = [_BASE]

    if profile.data:
        lines = "\n".join(f"  {k}: {v}" for k, v in profile.data.items())
        parts.append(f"## User Profile\n{lines}")

    if task is not None:
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
