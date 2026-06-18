from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table

from shared.cli_helpers import pick_provider
from shared.pricing import cost
from week_03.agent import Agent
from week_03.learn import extract_preferences, run_onboarding
from week_03.memory import (
    ProfileStore,
    ShortTermStore,
    TaskContext,
    WorkingStore,
    load_active_task_id,
    set_active_task_id,
    slug,
)
from week_03.pipeline import run_pipeline
from week_03.prompt_builder import build_system
from week_03.state import TransitionError, validate_transition
from week_03.stats import TokenStats

console = Console()


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


COMMANDS = {
    "/profile show": "print long-term profile",
    "/profile set <k> <v>": "upsert key in long-term profile",
    "/profile forget <k>": "remove key from profile",
    "/profile learn on|off": "toggle auto-capture of durable prefs",
    "/profile onboard": "rerun onboarding questions",
    "/run <description>": "create/activate task and run pipeline through all stages",
    "/resume": "continue active task pipeline from its persisted stage",
    "/auto on|off": "toggle auto-advance (no per-stage confirmation)",
    "/task new <name>": "create task in PLANNING",
    "/task show": "print current working memory",
    "/task status <state>": "move task state (forward, or roll back EXEC→PLAN / VALID→EXEC)",
    "/task plan <text>": "set the task plan (PLANNING)",
    "/task decision <text>": "append an accepted decision",
    "/task note <text>": "append note to working memory",
    "/task validate <text>": "set validation result (VALIDATION)",
    "/task reset": "wipe task content, return to PLANNING",
    "/clear": "clear short-term history only (profile + task untouched)",
    "/switch": "switch provider/model (all memory preserved)",
    "/help": "show this help",
    "exit / quit": "quit",
}


def _print_help() -> None:
    t = Table(show_header=False, box=None, padding=(0, 2))
    for cmd, desc in COMMANDS.items():
        t.add_row(f"[cyan]{cmd}[/]", f"[dim]{desc}[/]")
    console.print(t)
    console.print()


def _print_profile(profile_store: ProfileStore) -> None:
    p = profile_store.load()
    if not p.data:
        console.print("[dim]Profile is empty. Use /profile set <k> <v> to add entries.[/]\n")
        return
    t = Table(show_header=False, box=None, padding=(0, 2))
    for k, v in p.data.items():
        t.add_row(f"[cyan]{k}[/]", v)
    title = f"Long-term profile · {len(p.data)} entries · {profile_store.path}"
    console.print(Panel(t, title=title, expand=False))
    console.print()


def _print_task(ctx: TaskContext) -> None:
    rows = [
        f"[bold]name:[/]  {ctx.name}",
        f"[bold]state:[/] [yellow]{ctx.state}[/]",
    ]
    if ctx.plan:
        rows.append(f"[bold]plan:[/]  {ctx.plan}")
    for d in ctx.decisions:
        rows.append(f"[bold]decision:[/] {d}")
    for n in ctx.notes:
        rows.append(f"[bold]note:[/]     {n}")
    if ctx.validation:
        rows.append(f"[bold]validation:[/] {ctx.validation}")
    if ctx.current_step:
        rows.append(f"[bold]current_step:[/] {ctx.current_step}")
    if ctx.expected_action:
        rows.append(f"[bold]expected_action:[/] {ctx.expected_action}")
    if ctx.updated_at:
        rows.append(f"[bold]updated_at:[/] [dim]{ctx.updated_at}[/]")
    console.print(Panel("\n".join(rows), title=f"Working memory · {ctx.task_id}", expand=False))
    console.print()


def run(
    user: str = "default",
    chat: str = "default",
    *,
    fresh: bool = False,
    learn: bool = False,
    no_onboard: bool = False,
    auto: bool = False,
) -> None:
    console.print(Panel("[bold]Week 03 · Stateful Agent[/]", expand=False))
    mode = "[yellow]fresh session[/]" if fresh else "[dim]resuming history[/]"
    learn_flag = "[green]learn=on[/]" if learn else "[dim]learn=off[/]"
    onboard_flag = "[dim]onboard=skipped[/]" if no_onboard else "[yellow]onboard=first-run[/]"
    auto_flag = "[green]auto=on[/]" if auto else "[dim]auto=off[/]"
    console.print(
        f"[dim]user=[cyan]{user}[/]  chat=[cyan]{chat}[/]  {mode}  "
        f"{learn_flag}  {onboard_flag}  {auto_flag}[/]\n"
    )

    profile_store = ProfileStore(user)
    if not no_onboard:
        run_onboarding(profile_store)
    short_term = ShortTermStore(user, chat, fresh=fresh)
    stats = TokenStats()

    # mutable references so the build_system closure always sees current values
    active_task: TaskContext | None = None
    working_store: WorkingStore | None = None

    # restore active task from pointer
    task_id = load_active_task_id(user)
    if task_id:
        ws = WorkingStore(user, task_id)
        if ws.exists():
            working_store = ws
            active_task = ws.load()
            console.print(
                f"[dim]Resumed task: [cyan]{active_task.name}[/] ({active_task.state})[/]\n"
            )
        else:
            console.print(f"[yellow]Pointer references missing task {task_id!r} — cleared.[/]\n")
            set_active_task_id(user, None)

    auto_mode = auto

    def _build_system() -> str:
        return build_system(profile_store.load(), active_task)

    provider = pick_provider()
    agent = Agent(provider, short_term, _build_system, stats)

    console.print(Rule(f"[green]{agent.provider_name}[/] · [dim]{agent.model_id}[/]"))
    console.print("[dim]Type a message or [bold]/help[/] for commands.[/]\n")

    while True:
        user_input = Prompt.ask("[bold blue]You[/]").strip()

        if user_input.lower() in {"exit", "quit", "выход"}:
            console.print("\n[dim]Bye![/]")
            break

        if user_input == "/help":
            _print_help()
            continue

        if user_input == "/switch":
            console.print()
            provider = pick_provider()
            agent.switch_provider(provider)
            console.print(Rule(f"[green]{agent.provider_name}[/] · [dim]{agent.model_id}[/]"))
            continue

        if user_input == "/clear":
            short_term.clear()
            console.print("[dim]Short-term cleared. Profile and task untouched.[/]\n")
            continue

        if user_input == "/profile show":
            _print_profile(profile_store)
            continue

        if user_input.startswith("/profile set "):
            rest = user_input[len("/profile set ") :].strip()
            parts = rest.split(None, 1)
            if len(parts) < 2:
                console.print("[red]Usage: /profile set <key> <value>[/]\n")
                continue
            key, value = parts[0], _unquote(parts[1])
            profile_store.upsert(key, value)
            console.print(f"[dim]Profile: [cyan]{key}[/] = {value}[/]\n")
            continue

        if user_input.startswith("/profile forget "):
            key = user_input[len("/profile forget ") :].strip()
            if not key:
                console.print("[red]Usage: /profile forget <key>[/]\n")
                continue
            p = profile_store.load()
            if key in p.data:
                del p.data[key]
                profile_store.save(p)
                console.print(f"[dim]Profile: removed [cyan]{key}[/][/]")
            else:
                console.print(f"[yellow]Key {key!r} not in profile.[/]\n")
            continue

        if user_input == "/profile learn on":
            learn = True
            console.print("[dim]Learn mode: on (auto-capture enabled)[/]\n")
            continue
        if user_input == "/profile learn off":
            learn = False
            console.print("[dim]Learn mode: off[/]\n")
            continue

        if user_input == "/profile onboard":
            run_onboarding(profile_store)
            continue

        if user_input == "/auto on":
            auto_mode = True
            console.print("[dim]auto-advance: on[/]\n")
            continue
        if user_input == "/auto off":
            auto_mode = False
            console.print("[dim]auto-advance: off[/]\n")
            continue

        if user_input.startswith("/run "):
            desc = _unquote(user_input[len("/run ") :])
            if not desc:
                console.print("[red]Usage: /run <task description>[/]\n")
                continue
            new_id = slug(desc)
            new_ws = WorkingStore(user, new_id)
            ctx = TaskContext(task_id=new_id, name=desc, state="PLANNING")
            new_ws.save(ctx)
            set_active_task_id(user, new_id)
            working_store = new_ws
            active_task = ctx
            console.print(f"[dim]Task [cyan]{desc}[/] created (id=[cyan]{new_id}[/]).[/]\n")
            run_pipeline(
                active_task,
                profile_store,
                provider,
                working_store,
                auto=auto_mode,
                console=console,
                stats=stats,
            )
            active_task = working_store.load()
            continue

        if user_input == "/resume":
            if active_task is None or working_store is None:
                console.print("[yellow]No active task to resume. Use /run <desc> first.[/]\n")
                continue
            active_task = working_store.load()
            run_pipeline(
                active_task,
                profile_store,
                provider,
                working_store,
                auto=auto_mode,
                console=console,
                stats=stats,
            )
            active_task = working_store.load()
            continue

        if user_input.startswith("/task new "):
            name = _unquote(user_input[len("/task new ") :])
            if not name:
                console.print("[red]Usage: /task new <name>[/]\n")
                continue
            new_id = slug(name)
            new_ws = WorkingStore(user, new_id)
            ctx = TaskContext(task_id=new_id, name=name, state="PLANNING")
            new_ws.save(ctx)
            set_active_task_id(user, new_id)
            working_store = new_ws
            active_task = ctx
            console.print(
                f"[dim]Task [cyan]{name}[/] created (id=[cyan]{new_id}[/], PLANNING).[/]\n"
            )
            continue

        if user_input == "/task show":
            if active_task is None:
                console.print("[yellow]No active task. Use /task new <name> first.[/]\n")
            else:
                _print_task(active_task)
            continue

        if user_input.startswith("/task status "):
            if active_task is None or working_store is None:
                console.print("[yellow]No active task. Use /task new <name> first.[/]\n")
                continue
            target = user_input[len("/task status ") :].strip()
            result = validate_transition(active_task.state, target)
            if isinstance(result, TransitionError):
                console.print(f"[red]{result.message}[/]\n")
            else:
                active_task.state = result.new_state.value
                working_store.save(active_task)
                console.print(f"[dim]Task state → [yellow]{active_task.state}[/][/]\n")
            continue

        if user_input.startswith("/task plan "):
            if active_task is None or working_store is None:
                console.print("[yellow]No active task. Use /task new <name> first.[/]\n")
                continue
            plan = _unquote(user_input[len("/task plan ") :])
            if not plan:
                console.print("[red]Usage: /task plan <text>[/]\n")
                continue
            active_task.plan = plan
            working_store.save(active_task)
            console.print("[dim]Plan set in working memory.[/]\n")
            continue

        if user_input.startswith("/task decision "):
            if active_task is None or working_store is None:
                console.print("[yellow]No active task. Use /task new <name> first.[/]\n")
                continue
            decision = _unquote(user_input[len("/task decision ") :])
            if not decision:
                console.print("[red]Usage: /task decision <text>[/]\n")
                continue
            active_task.decisions.append(decision)
            working_store.save(active_task)
            console.print("[dim]Decision added to working memory.[/]\n")
            continue

        if user_input.startswith("/task validate "):
            if active_task is None or working_store is None:
                console.print("[yellow]No active task. Use /task new <name> first.[/]\n")
                continue
            validation = _unquote(user_input[len("/task validate ") :])
            if not validation:
                console.print("[red]Usage: /task validate <text>[/]\n")
                continue
            active_task.validation = validation
            working_store.save(active_task)
            console.print("[dim]Validation result set in working memory.[/]\n")
            continue

        if user_input.startswith("/task note "):
            if active_task is None or working_store is None:
                console.print("[yellow]No active task. Use /task new <name> first.[/]\n")
                continue
            note = _unquote(user_input[len("/task note ") :])
            if not note:
                console.print("[red]Usage: /task note <text>[/]\n")
                continue
            active_task.notes.append(note)
            working_store.save(active_task)
            console.print("[dim]Note added to working memory.[/]\n")
            continue

        if user_input == "/task reset":
            if active_task is None or working_store is None:
                console.print("[yellow]No active task. Use /task new <name> first.[/]\n")
                continue
            active_task.state = "PLANNING"
            active_task.plan = ""
            active_task.decisions = []
            active_task.notes = []
            active_task.validation = ""
            working_store.save(active_task)
            console.print(f"[dim]Task [cyan]{active_task.name}[/] reset to PLANNING.[/]\n")
            continue

        if not user_input:
            continue

        if user_input.startswith("/"):
            console.print(f"[red]Unknown command:[/] {user_input}  Type /help.\n")
            continue

        console.print(f"\n[bold green]{agent.provider_name}[/]:")
        try:
            for token in agent.ask_stream(user_input):
                console.print(token, end="", highlight=False, markup=False)
        except Exception as e:
            short_term.pop_last()
            console.print(f"\n[red]Error:[/] {e}\n")
            continue

        console.print("\n")

        if agent.last_usage is not None:
            u = agent.last_usage
            turn = cost(agent.model_id, u.prompt_tokens, u.completion_tokens)
            console.print(
                f"[dim]Tokens: {u.prompt_tokens} prompt + {u.completion_tokens} completion "
                f"= {u.prompt_tokens + u.completion_tokens}"
                f" | Cost: ${turn:.6f} | Session: {stats.total} tokens (${stats.cost:.6f})[/]"
            )
        console.print()

        if learn and user_input and not user_input.startswith("/"):
            updates = extract_preferences(
                user_input, profile_store.load().data, agent.client, agent.model_id
            )
            for k, v in updates.items():
                profile_store.upsert(k, v)
                console.print(f"[dim]Learned: {k}={v}[/]")
