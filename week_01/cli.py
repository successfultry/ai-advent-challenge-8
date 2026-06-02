from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table

from week_01.client import available_providers, get_client, stream_response

console = Console()

COMMANDS = {
    "/switch": "switch model",
    "/clear":  "clear chat history",
    "/help":   "show this help",
    "exit":    "quit",
}


def print_help() -> None:
    t = Table(show_header=False, box=None, padding=(0, 2))
    for cmd, desc in COMMANDS.items():
        t.add_row(f"[cyan]{cmd}[/]", f"[dim]{desc}[/]")
    console.print(t)


def pick_provider() -> str:
    providers = available_providers()
    if not providers:
        console.print(
            "[bold red]No API keys found.[/] "
            "Copy [cyan].env.example[/] → [cyan].env[/] and fill in your keys."
        )
        sys.exit(1)

    console.print(Panel("[bold]Available models[/]", expand=False))
    for i, name in enumerate(providers, 1):
        console.print(f"  [cyan]{i}[/]. {name}")

    while True:
        choice = Prompt.ask("\nSelect model", default="1")
        if choice.lower() in {"exit", "quit", "выход"}:
            console.print("\n[dim]Bye![/]")
            sys.exit(0)
        if choice.isdigit() and 1 <= int(choice) <= len(providers):
            return providers[int(choice) - 1]
        console.print("[red]Invalid choice, try again.[/]")


def chat_loop(provider_name: str) -> bool:
    client, model_id = get_client(provider_name)
    messages: list[dict[str, str]] = []

    console.print(Rule(f"[green]{provider_name}[/] · [dim]{model_id}[/]"))
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
            messages.clear()
            console.print("[dim]History cleared.[/]\n")
            continue

        if user_input == "/help":
            print_help()
            console.print()
            continue

        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})
        console.print(f"\n[bold green]{provider_name}[/]:")
        full_response: list[str] = []

        usage = None
        try:
            for chunk in stream_response(client, model_id, messages):
                if isinstance(chunk, dict):
                    usage = chunk.get("usage")
                else:
                    console.print(chunk, end="", highlight=False)
                    full_response.append(chunk)
        except Exception as e:
            console.print(f"\n[red]Error:[/] {e}")
            messages.pop()
            continue

        response_text = "".join(full_response)
        if usage:
            console.print(
                f"\n[dim]↑ {usage.prompt_tokens} · ↓ {usage.completion_tokens} tokens[/]"
            )
        console.print()
        messages.append({"role": "assistant", "content": response_text})


def run() -> None:
    console.print(Panel("[bold]Week 01 · LLM Playground[/]", expand=False))
    while True:
        provider = pick_provider()
        switch = chat_loop(provider)
        if not switch:
            break
