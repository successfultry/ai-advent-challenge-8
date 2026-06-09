from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table

from shared.cli_helpers import pick_provider
from week_02.agent import Agent
from week_02.memory import SessionMemory

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


def run() -> None:
    console.print(Panel("[bold]Week 02 · Agent Chat[/]", expand=False))
    memory = SessionMemory()

    while True:
        provider = pick_provider()
        agent = Agent(provider, memory, system_prompt=SYSTEM_PROMPT)
        switch = _chat_loop(agent)
        if not switch:
            break
