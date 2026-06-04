from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table

from week_01.client import available_providers, get_client, get_response, stream_response

console = Console()

COMMANDS = {
    "/params": "configure API params (max_tokens, stop, json) — toggle on/off",
    "/params off": "disable API params, back to raw mode",
    "/hint": "show prompt-constrained template to copy-paste",
    "/switch": "switch model",
    "/clear": "clear chat history",
    "/help": "show this help",
    "exit": "quit",
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


def ask_params() -> dict:
    console.print(Panel("[bold]API params[/] (Enter = skip)", expand=False))

    raw = Prompt.ask("  max_tokens", default="")
    max_tokens = int(raw) if raw.strip().isdigit() else None

    raw = Prompt.ask("  stop sequence", default="")
    stop = [raw.strip()] if raw.strip() else None

    raw = Prompt.ask("  json mode? (y/n)", default="n")
    response_format = {"type": "json_object"} if raw.strip().lower() == "y" else None

    params: dict = {}
    if max_tokens is not None:
        params["max_tokens"] = max_tokens
    if stop is not None:
        params["stop"] = stop
    if response_format is not None:
        params["response_format"] = response_format

    if params:
        parts = []
        if "max_tokens" in params:
            parts.append(f"max_tokens={params['max_tokens']}")
        if "stop" in params:
            parts.append(f"stop={params['stop']}")
        if "response_format" in params:
            parts.append("json=on")
        console.print(f"[green]Params active:[/] {', '.join(parts)}\n")
    else:
        console.print("[dim]No params set — raw mode.[/]\n")

    return params


def print_hint() -> None:
    console.print(
        Panel(
            "[bold]Prompt-constrained template[/]\n\n"
            "[dim]Copy, paste, edit — then send as a regular message:[/]\n\n"
            '<ваш вопрос>. Ответь в формате JSON: {"answer": "...", "summary": "..."}. '
            "Не больше 50 слов. Закончи словом END.\n\n"
            "[dim]EN version:[/]\n"
            '<your question>. Respond in JSON: {"answer": "...", "summary": "..."}. '
            "Keep under 50 words. End with the word END.",
            expand=False,
        )
    )
    console.print()


def chat_loop(provider_name: str) -> bool:
    client, model_id = get_client(provider_name)
    messages: list[dict[str, str]] = []
    api_params: dict = {}

    console.print(Rule(f"[green]{provider_name}[/] · [dim]{model_id}[/]"))
    console.print("[dim]Type a message or [bold]/help[/] for commands.[/]\n")

    while True:
        if api_params:
            tag = ", ".join(
                f"{k}={v}" if k != "response_format" else "json=on" for k, v in api_params.items()
            )
            prompt_label = f"[bold blue]You[/] [dim]\\[{tag}][/]"
        else:
            prompt_label = "[bold blue]You[/]"
        user_input = Prompt.ask(prompt_label).strip()

        if user_input.lower() in {"exit", "quit", "выход"}:
            console.print("\n[dim]Bye![/]")
            return False

        if user_input == "/switch":
            console.print()
            return True

        if user_input == "/params off":
            api_params = {}
            console.print("[dim]Params off — raw mode.[/]\n")
            continue

        if user_input == "/params":
            if messages:
                console.print(
                    "[dim]💡 Tip: /clear history before comparing for cleaner results.[/]"
                )
            api_params = ask_params()
            continue

        if user_input == "/hint":
            print_hint()
            continue

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

        if api_params:
            # non-streaming: get_response returns content + finish_reason + usage
            try:
                content, finish_reason, usage = get_response(
                    client,
                    model_id,
                    messages,
                    **api_params,
                )
                console.print(content)
                parts = []
                if usage:
                    parts.append(f"↑ {usage.prompt_tokens} · ↓ {usage.completion_tokens}")
                parts.append(f"finish: [bold]{finish_reason}[/]")
                console.print(f"\n[dim]{' · '.join(parts)} tokens[/]")
            except Exception as e:
                console.print(f"\n[red]Error:[/] {e}")
                messages.pop()
                continue
            messages.append({"role": "assistant", "content": content})
        else:
            # streaming: token-by-token
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
            messages.append({"role": "assistant", "content": response_text})

        console.print()


def run() -> None:
    console.print(Panel("[bold]Week 01 · LLM Playground[/]", expand=False))
    while True:
        provider = pick_provider()
        switch = chat_loop(provider)
        if not switch:
            break
