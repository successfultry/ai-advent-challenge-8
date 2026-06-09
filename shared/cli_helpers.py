from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from shared.client import available_providers

console = Console()


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
