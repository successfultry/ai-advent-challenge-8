from __future__ import annotations

from functools import partial
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table

from shared.cli_helpers import pick_provider
from shared.client import get_client
from shared.pricing import cost
from week_02.agent import Agent
from week_02.context import SlidingWindowPolicy, SummaryPolicy
from week_02.memory import FileMemory
from week_02.stats import TokenStats
from week_02.summarizer import summarize

console = Console()

SYSTEM_PROMPT = (
    "You are a concise assistant. Answer precisely and to the point, "
    "in the same language the user writes in."
)

COMMANDS = {
    "/clear": "clear chat history",
    "/switch": "switch model (history is preserved)",
    "/help": "show this help",
    "exit / quit / выход": "quit",
}


def _print_help() -> None:
    t = Table(show_header=False, box=None, padding=(0, 2))
    for cmd, desc in COMMANDS.items():
        t.add_row(f"[cyan]{cmd}[/]", f"[dim]{desc}[/]")
    console.print(t)
    console.print()


def _chat_loop(agent: Agent) -> bool:
    console.print(Rule(f"[green]{agent.provider_name}[/] · [dim]{agent.model_id}[/]"))
    console.print("[dim]Type a message or [bold]/help[/] for commands.[/]\n")

    while True:
        user_input = Prompt.ask("[bold blue]You[/]").strip()

        if user_input.lower() in {"exit", "quit", "выход"}:
            console.print("\n[dim]Bye![/]")
            return False

        if user_input == "/switch":
            console.print()
            return True

        if user_input == "/clear":
            agent.reset()
            console.print("[dim]History cleared.[/]\n")
            continue

        if user_input == "/help":
            _print_help()
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

        if agent.last_compression is not None and agent.last_compression.changed:
            console.print("[dim cyan]Context compressed (summary updated)[/]")

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
    memory = FileMemory(filepath)
    stats = TokenStats()
    provider = pick_provider()

    if policy_name == "sliding":
        policy = SlidingWindowPolicy()
    else:
        client, model_id = get_client(provider)
        summary_path = Path("data") / f"summary_{user}.json"
        summarize_fn = partial(summarize, client, model_id)
        policy = SummaryPolicy(summarize_fn, summary_path, summary_model_id=model_id)

    while True:
        agent = Agent(provider, memory, policy, stats, system_prompt=SYSTEM_PROMPT)
        switch = _chat_loop(agent)
        if not switch:
            break
        provider = pick_provider()
