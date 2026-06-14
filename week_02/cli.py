from __future__ import annotations

from functools import partial
from pathlib import Path

from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table

from shared.cli_helpers import pick_provider
from shared.client import get_client
from shared.pricing import cost
from week_02.agent import Agent
from week_02.context import (
    CompressionResult,
    ContextPolicy,
    FactsPolicy,
    FactsResult,
    SlidingWindowPolicy,
    SummaryPolicy,
)
from week_02.facts import extract
from week_02.memory import BranchingMemory
from week_02.stats import TokenStats
from week_02.summarizer import summarize

console = Console()

SYSTEM_PROMPT = (
    "You are a concise assistant. Answer precisely and to the point, "
    "in the same language the user writes in."
)

COMMANDS = {
    "/clear": "clear chat history and policy state",
    "/switch": "switch model (history preserved)",
    "/policy <sliding|facts|summary>": "swap context strategy at runtime",
    "/branch new <name>": "fork current branch into a new one",
    "/branch switch <name>": "switch to an existing branch",
    "/branch list": "list all branches",
    "/help": "show this help",
    "exit / quit / выход": "quit",
}


def _print_help() -> None:
    t = Table(show_header=False, box=None, padding=(0, 2))
    for cmd, desc in COMMANDS.items():
        t.add_row(f"[cyan]{cmd}[/]", f"[dim]{desc}[/]")
    console.print(t)
    console.print()


def _policy_path(kind: str, user: str, branch: str) -> Path:
    # main branch keeps legacy flat filenames for backward compat with day-9 data
    if branch == "main":
        return Path("data") / f"{kind}_{user}.json"
    return Path("data") / f"{kind}_{user}__{branch}.json"


def make_policy(
    name: str,
    *,
    client: OpenAI,
    model_id: str,
    user: str,
    branch: str,
) -> ContextPolicy:
    if name == "sliding":
        return SlidingWindowPolicy()
    if name == "summary":
        summarize_fn = partial(summarize, client, model_id)
        return SummaryPolicy(
            summarize_fn, _policy_path("summary", user, branch), summary_model_id=model_id
        )
    if name == "facts":
        extract_fn = partial(extract, client, model_id)
        return FactsPolicy(extract_fn, _policy_path("facts", user, branch), facts_model_id=model_id)
    raise ValueError(f"Unknown policy: {name!r}")


def _chat_loop(agent: Agent, policy_name: str, user: str) -> tuple[bool, str]:
    console.print(
        Rule(
            f"[green]{agent.provider_name}[/] · [dim]{agent.model_id}[/]"
            f" · policy=[cyan]{policy_name}[/]"
        )
    )
    console.print("[dim]Type a message or [bold]/help[/] for commands.[/]\n")

    while True:
        user_input = Prompt.ask("[bold blue]You[/]").strip()

        if user_input.lower() in {"exit", "quit", "выход"}:
            console.print("\n[dim]Bye![/]")
            return False, policy_name

        if user_input == "/switch":
            console.print()
            return True, policy_name

        if user_input == "/clear":
            agent.reset()
            console.print("[dim]History cleared.[/]\n")
            continue

        if user_input == "/help":
            _print_help()
            continue

        if user_input.startswith("/policy "):
            new_name = user_input.split(None, 1)[1].strip()
            if new_name not in ("sliding", "facts", "summary"):
                console.print(
                    f"[red]Unknown policy:[/] {new_name!r}. Use: sliding, facts, summary\n"
                )
                continue
            branch = agent.memory.active if isinstance(agent.memory, BranchingMemory) else "main"
            agent.policy = make_policy(
                new_name, client=agent.client, model_id=agent.model_id, user=user, branch=branch
            )
            policy_name = new_name
            console.print(f"[dim]Policy switched to [cyan]{new_name}[/].[/]\n")
            continue

        if user_input.startswith("/branch"):
            parts = user_input.split()
            if not isinstance(agent.memory, BranchingMemory):
                console.print("[red]Branching not available for this memory type.[/]\n")
                continue
            if len(parts) >= 3 and parts[1] == "new":
                branch_name = parts[2]
                try:
                    agent.memory.create_branch(branch_name)
                    agent.policy = make_policy(
                        policy_name,
                        client=agent.client,
                        model_id=agent.model_id,
                        user=user,
                        branch=agent.memory.active,
                    )
                    console.print(
                        f"[dim]Created and switched to branch [cyan]{branch_name}[/].[/]\n"
                    )
                except ValueError as e:
                    console.print(f"[red]{e}[/]\n")
            elif len(parts) >= 3 and parts[1] == "switch":
                branch_name = parts[2]
                try:
                    agent.memory.switch_branch(branch_name)
                    agent.policy = make_policy(
                        policy_name,
                        client=agent.client,
                        model_id=agent.model_id,
                        user=user,
                        branch=agent.memory.active,
                    )
                    console.print(f"[dim]Switched to branch [cyan]{branch_name}[/].[/]\n")
                except ValueError as e:
                    console.print(f"[red]{e}[/]\n")
            elif len(parts) >= 2 and parts[1] == "list":
                branches = agent.memory.list_branches()
                active = agent.memory.active
                for b in branches:
                    marker = " [green]← active[/]" if b == active else ""
                    console.print(f"  [cyan]{b}[/]{marker}")
                console.print()
            else:
                console.print(
                    "[dim]Usage: /branch new <name> | /branch switch <name> | /branch list[/]\n"
                )
            continue

        if not user_input:
            continue

        console.print(f"\n[bold green]{agent.provider_name}[/]:")
        try:
            for token in agent.ask_stream(user_input):
                console.print(token, end="", highlight=False, markup=False)
        except Exception as e:
            agent.memory.pop_last()
            console.print(f"\n[red]Error:[/] {e}")
            console.print("\n")
            continue

        console.print("\n")

        if hasattr(agent.policy, "last_dropped") and agent.policy.last_dropped > 0:
            console.print(
                f"[yellow]Context limit reached. Dropped {agent.policy.last_dropped} "
                f"old messages — the model no longer sees them.[/]"
            )

        if agent.last_result is not None and agent.last_result.changed:
            r = agent.last_result
            if isinstance(r, CompressionResult):
                console.print(
                    f"[dim cyan]Context compressed (summary updated, folded {r.dropped} msgs)[/]"
                )
            elif isinstance(r, FactsResult):
                console.print(f"[dim cyan]Facts updated ({r.facts_count} facts)[/]")

        if agent.last_usage is not None:
            u = agent.last_usage
            turn = cost(agent.model_id, u.prompt_tokens, u.completion_tokens)
            console.print(
                f"[dim]Tokens: {u.prompt_tokens} prompt + {u.completion_tokens} completion"
                f" = {u.prompt_tokens + u.completion_tokens}"
                f" | Cost: ${turn:.6f}"
                f" | Session: {agent.stats.total} tokens (${agent.stats.cost:.6f})[/]"
            )
        else:
            console.print("[dim]Tokens: n/a[/]")

        console.print()


def run(user: str = "default", policy_name: str = "sliding") -> None:
    console.print(Panel("[bold]Week 02 · Agent Chat[/]", expand=False))
    filepath = Path("data") / f"history_{user}.json"
    pointer_path = Path("data") / f"branches_{user}.json"
    memory = BranchingMemory(filepath, pointer_path)
    stats = TokenStats()
    provider = pick_provider()
    client, model_id = get_client(provider)
    policy = make_policy(
        policy_name, client=client, model_id=model_id, user=user, branch=memory.active
    )

    while True:
        agent = Agent(provider, memory, policy, stats, system_prompt=SYSTEM_PROMPT)
        switch, policy_name = _chat_loop(agent, policy_name, user)
        if not switch:
            break
        provider = pick_provider()
        client, model_id = get_client(provider)
        policy = make_policy(
            policy_name, client=client, model_id=model_id, user=user, branch=memory.active
        )
