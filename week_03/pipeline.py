from __future__ import annotations

import json

from rich.console import Console
from rich.prompt import Prompt

from week_03.agent import Agent
from week_03.memory import ProfileStore, ShortTermStore, TaskContext, WorkingStore
from week_03.prompt_builder import TaskState, build_stage_system
from week_03.state import TransitionError, next_stage, validate_transition
from week_03.stats import TokenStats


def _parse_artifact(raw: str) -> dict | None:
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return None


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

    raw = agent.ask_once(f"Task: {task.name}")
    console.print(f"[dim]{raw}[/]\n")

    artifact = _parse_artifact(raw)
    if artifact is None:
        console.print("[yellow]Malformed JSON. Retrying once...[/]")
        raw = agent.ask_once("Return ONLY valid JSON matching the required schema.")
        console.print(f"[dim]{raw}[/]\n")
        artifact = _parse_artifact(raw)

    if artifact is None:
        task.expected_action = "retry stage output format"
        task.last_stage_output = raw[:500]
        working_store.save(task)
        console.print(
            f"[red]Stage {stage.value} failed to produce valid JSON. "
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
    """Deterministic next stage. Code decides — never the LLM.

    VALIDATION branches on the artifact's status field (PASS -> DONE, FAIL ->
    rollback to EXECUTION). Every other stage follows the canonical forward edge.
    """
    if stage == TaskState.VALIDATION:
        status = str(artifact.get("status", "")).upper()
        return TaskState.DONE if status == "PASS" else TaskState.EXECUTION
    return next_stage(stage.value)


def run_pipeline(
    task: TaskContext,
    profile_store: ProfileStore,
    provider: str,
    working_store: WorkingStore,
    *,
    auto: bool,
    console: Console,
) -> None:
    stats = TokenStats()
    runs = 0

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
            _run_stage(cur, task, profile_store, provider, working_store, stats, console)
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

        nxt = _target_after(cur, artifact)
        if nxt is None:
            break

        if cur == TaskState.VALIDATION and nxt == TaskState.EXECUTION:
            console.print("[yellow]Validation FAILED — rolling back to EXECUTION.[/]")

        if not auto:
            ans = (
                Prompt.ask(
                    f"[green]Stage {cur.value} done. Proceed to {nxt.value}?[/] [ok/pause/abort]",
                    default="ok",
                )
                .strip()
                .lower()
            )
            if ans == "pause":
                console.print("[dim]Pipeline paused. Use /resume to continue.[/]\n")
                return
            if ans == "abort":
                console.print("[dim]Pipeline aborted.[/]\n")
                return

        result = validate_transition(task.state, nxt.value)
        if isinstance(result, TransitionError):
            console.print(f"[red]{result.message}[/]\n")
            return
        task.state = result.new_state.value
        working_store.save(task)
        console.print(f"[dim]→ {task.state}[/]\n")
