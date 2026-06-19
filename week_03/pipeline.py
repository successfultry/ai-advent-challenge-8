from __future__ import annotations

import json

from rich.console import Console
from rich.prompt import Prompt

from week_03.agent import Agent
from week_03.memory import (
    ProfileStore,
    ShortTermStore,
    TaskContext,
    WorkingStore,
    load_invariants_text,
)
from week_03.prompt_builder import TaskState, build_stage_system
from week_03.state import TransitionError, next_stage, validate_transition
from week_03.stats import TokenStats

# Required keys per stage — enforces the artifact contract, not just "is JSON".
_REQUIRED_KEYS: dict[TaskState, set[str]] = {
    TaskState.PLANNING: {"status", "reason", "plan", "current_step", "expected_action"},
    TaskState.EXECUTION: {"result", "artifacts", "current_step", "expected_action"},
    TaskState.VALIDATION: {"status", "issues", "rollback_to", "current_step", "expected_action"},
    TaskState.DONE: {"summary", "current_step", "expected_action"},
}


def _parse_artifact(raw: str, stage: TaskState) -> dict | None:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not _REQUIRED_KEYS[stage] <= data.keys():
        return None
    if stage == TaskState.PLANNING:
        status = data.get("status")
        reason = data.get("reason")
        plan = data.get("plan")

        if status not in {"ACCEPTED", "REJECTED"}:
            return None
        if not isinstance(reason, str):
            return None
        if not isinstance(plan, list):
            return None

        if status == "ACCEPTED":
            if reason != "none":
                return None
            if not plan:
                return None

        if status == "REJECTED":
            if not reason or reason == "none":
                return None
            if plan != []:
                return None
            if data.get("current_step") != "rejected":
                return None
            if data.get("expected_action") != "revise request":
                return None
    if stage == TaskState.VALIDATION:
        status = str(data.get("status", "")).upper()
        rb = str(data.get("rollback_to", "")).lower()
        if status not in {"PASS", "FAIL"}:
            return None
        if rb not in {"execution", "planning", "none"}:
            return None
        # status and rollback_to must agree — a FAIL with rollback_to=none (or a
        # PASS that still wants a rollback) is a contradictory verdict; reject it
        # so the inline retry forces the model to commit to one answer.
        if status == "PASS" and rb != "none":
            return None
        if status == "FAIL" and rb not in {"execution", "planning"}:
            return None
    return data


def _run_stage(
    stage: TaskState,
    task: TaskContext,
    profile_store: ProfileStore,
    provider: str,
    working_store: WorkingStore,
    stats: TokenStats,
    console: Console,
) -> dict | None:
    short_term = ShortTermStore(task.task_id, stage.value, fresh=True)

    def _build() -> str:
        return build_stage_system(profile_store.load(), task, stage)

    agent = Agent(provider, short_term, _build, stats)

    console.print(f"\n[bold cyan]Stage: {stage.value}[/]\n")

    try:
        raw = agent.ask_once(f"Task: {task.name}")
        console.print(f"[dim]{raw}[/]\n")

        artifact = _parse_artifact(raw, stage)
        if artifact is None:
            console.print("[yellow]Malformed artifact. Retrying once...[/]")
            raw = agent.ask_once("Return ONLY valid JSON matching the required schema.")
            console.print(f"[dim]{raw}[/]\n")
            artifact = _parse_artifact(raw, stage)
    except Exception as e:
        task.expected_action = "retry stage llm call"
        working_store.save(task)
        console.print(
            f"[red]Stage {stage.value} LLM call failed: {e}. "
            "State preserved — use /resume to retry.[/]\n"
        )
        return None

    if artifact is None:
        task.expected_action = "retry stage output format"
        task.last_stage_output = raw[:500]
        working_store.save(task)
        console.print(
            f"[red]Stage {stage.value} failed the artifact contract. "
            "State not advanced. Use /resume to retry.[/]\n"
        )
        return None

    task.last_stage_output = json.dumps(artifact, ensure_ascii=False)[:500]
    task.current_step = artifact.get("current_step", stage.value.lower())
    task.expected_action = artifact.get("expected_action", "")

    if stage == TaskState.PLANNING and artifact.get("plan"):
        plan = artifact["plan"]
        task.plan = "\n".join(plan) if isinstance(plan, list) else str(plan)
    elif stage == TaskState.EXECUTION:
        result = artifact.get("result", "")
        if result:
            # keep only the latest execution output so VALIDATION (and rollback
            # loops) judge the current code, not a pile of stale attempts
            task.notes = [n for n in task.notes if not n.startswith("[execution]")]
            task.notes.append(f"[execution] {result}")
    elif stage == TaskState.VALIDATION:
        status = artifact.get("status", "?")
        issues = artifact.get("issues", [])
        task.validation = f"status={status} issues={issues}"
    elif stage == TaskState.DONE:
        summary = artifact.get("summary", "")
        if summary:
            task.notes.append(f"[summary] {summary}")

    working_store.save(task)
    return artifact


# Safety bound against EXECUTION <-> VALIDATION rollback loops in auto mode.
_MAX_STAGE_RUNS = 6


def _target_after(stage: TaskState, artifact: dict) -> TaskState | None:
    if stage == TaskState.VALIDATION:
        status = str(artifact.get("status", "")).upper()
        if status == "PASS":
            return TaskState.DONE
        rollback = str(artifact.get("rollback_to", "execution")).lower()
        return TaskState.PLANNING if rollback == "planning" else TaskState.EXECUTION
    return next_stage(stage.value)


def _ask(console: Console, prompt_text: str) -> str | None:
    try:
        return Prompt.ask(prompt_text, default="ok").strip().lower()
    except (KeyboardInterrupt, EOFError):
        console.print()
        return None


def run_pipeline(
    task: TaskContext,
    profile_store: ProfileStore,
    provider: str,
    working_store: WorkingStore,
    *,
    auto: bool,
    console: Console,
    stats: TokenStats,
) -> None:
    runs = 0

    if load_invariants_text() is None:
        console.print("[red]Invariant store missing/corrupt. Run /invariants init.[/]\n")
        return

    # Resume gate: a paused task carries `awaiting` (the next stage it stopped
    # before). The completed stage is NOT re-run; we only ask consent to advance.
    if task.awaiting:
        target = task.awaiting
        if not auto:
            ans = _ask(console, f"[green]Resume: proceed to {target}?[/] [ok/abort]")
            if ans != "ok":
                console.print(f"[dim]Still paused after {task.state}. /resume later.[/]\n")
                return
        res = validate_transition(task.state, target)
        if isinstance(res, TransitionError):
            console.print(f"[red]{res.message}[/]\n")
            return
        task.state = res.new_state.value
        task.awaiting = ""
        working_store.save(task)
        console.print(f"[dim]→ {task.state}[/]\n")

    while True:
        try:
            cur = TaskState(task.state.upper())
        except ValueError:
            cur = TaskState.PLANNING
            task.state = cur.value

        if cur == TaskState.DONE:
            if task.current_step == "done":
                console.print("[dim]Task is already DONE.[/]\n")
                return
            # terminal stage: emit the summary artifact, then finish
            artifact = _run_stage(cur, task, profile_store, provider, working_store, stats, console)
            if artifact is not None:
                console.print("[bold green]Pipeline complete.[/]\n")
            return

        runs += 1
        if runs > _MAX_STAGE_RUNS:
            task.expected_action = "manual review: too many stage iterations"
            working_store.save(task)
            console.print(
                "[red]Stage budget exhausted (possible execution/validation loop). "
                "Paused for manual review — use /resume to continue.[/]\n"
            )
            return

        artifact = _run_stage(cur, task, profile_store, provider, working_store, stats, console)
        if artifact is None:
            return

        if cur == TaskState.PLANNING and artifact.get("status") == "REJECTED":
            reason = artifact.get("reason", "unknown")
            task.expected_action = f"revise request: {reason}"
            working_store.save(task)
            console.print(f"[yellow]Task rejected by invariants: {reason}[/]\n")
            return

        nxt = _target_after(cur, artifact)
        if nxt is None:
            break

        if cur == TaskState.VALIDATION and nxt in {TaskState.EXECUTION, TaskState.PLANNING}:
            console.print(f"[yellow]Validation FAILED — rolling back to {nxt.value}.[/]")

        if not auto:
            ans = _ask(
                console,
                f"[green]Stage {cur.value} done. Proceed to {nxt.value}?[/] [ok/pause/abort]",
            )
            if ans == "abort":
                # abort does NOT advance and does NOT queue: state stays on cur
                console.print("[dim]Pipeline aborted.[/]\n")
                return
            if ans is None or ans == "pause":
                # pause keeps state on the completed stage and queues the next one
                # in `awaiting`; /resume asks consent before running it (abortable)
                task.awaiting = nxt.value
                working_store.save(task)
                console.print(
                    f"[dim]Paused after {cur.value}. /resume to continue (you can abort then).[/]\n"
                )
                return

        # ok (or auto): advance + persist, keep running
        result = validate_transition(task.state, nxt.value)
        if isinstance(result, TransitionError):
            console.print(f"[red]{result.message}[/]\n")
            return
        task.state = result.new_state.value
        working_store.save(task)
        console.print(f"[dim]→ {task.state}[/]\n")
