from __future__ import annotations

import json

from rich.console import Console
from rich.prompt import Prompt

from week_03.agent import Agent
from week_03.memory import ProfileStore, ShortTermStore, TaskContext, WorkingStore
from week_03.prompt_builder import TaskState, build_stage_system
from week_03.state import TransitionError, next_stage, validate_transition
from week_03.stats import TokenStats

# Required keys per stage — enforces the artifact contract, not just "is JSON".
_REQUIRED_KEYS: dict[TaskState, set[str]] = {
    TaskState.PLANNING: {"plan", "current_step", "expected_action"},
    TaskState.EXECUTION: {"result", "artifacts", "current_step", "expected_action"},
    TaskState.VALIDATION: {"status", "issues", "rollback_to", "current_step", "expected_action"},
    TaskState.DONE: {"summary", "current_step", "expected_action"},
}


def _parse_artifact(raw: str, stage: TaskState) -> dict | None:
    """Parse + validate against the stage's artifact contract.

    Returns None on invalid JSON, missing required keys, or (for VALIDATION) a
    status outside {PASS, FAIL}. None triggers the inline retry / pause path.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not _REQUIRED_KEYS[stage] <= data.keys():
        return None
    if stage == TaskState.PLANNING and not isinstance(data.get("plan"), list):
        return None
    if stage == TaskState.VALIDATION:
        if str(data.get("status", "")).upper() not in {"PASS", "FAIL"}:
            return None
        if str(data.get("rollback_to", "")).lower() not in {"execution", "planning", "none"}:
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
        if status == "PASS":
            return TaskState.DONE
        rollback = str(artifact.get("rollback_to", "execution")).lower()
        return TaskState.PLANNING if rollback == "planning" else TaskState.EXECUTION
    return next_stage(stage.value)


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

        nxt = _target_after(cur, artifact)
        if nxt is None:
            break

        if cur == TaskState.VALIDATION and nxt in {TaskState.EXECUTION, TaskState.PLANNING}:
            console.print(f"[yellow]Validation FAILED — rolling back to {nxt.value}.[/]")

        paused = False
        if not auto:
            ans = (
                Prompt.ask(
                    f"[green]Stage {cur.value} done. Proceed to {nxt.value}?[/] [ok/pause/abort]",
                    default="ok",
                )
                .strip()
                .lower()
            )
            if ans == "abort":
                # abort does NOT advance: state stays on the current stage
                console.print("[dim]Pipeline aborted.[/]\n")
                return
            paused = ans == "pause"

        # advance + persist BEFORE returning, so pause/exit is lossless and
        # /resume continues from the NEXT stage (no re-running the current one)
        result = validate_transition(task.state, nxt.value)
        if isinstance(result, TransitionError):
            console.print(f"[red]{result.message}[/]\n")
            return
        task.state = result.new_state.value
        working_store.save(task)
        console.print(f"[dim]→ {task.state}[/]\n")

        if paused:
            console.print("[dim]Pipeline paused. Use /resume to continue.[/]\n")
            return
