from __future__ import annotations

import json
import sys

from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table

from week_01.client import (
    available_providers,
    build_payload,
    get_client,
    get_response,
    stream_response,
)
from week_01.techniques import (
    JUDGE_TEMPLATE,
    META_STEP1_TEMPLATE,
    cot,
    direct,
    experts,
    is_russian,
)

console = Console()

DEFAULT_TEMPS = (0.0, 0.7, 1.2, 2.0)
DEFAULT_REPEATS = 3
DEFAULT_TEMP_MAX_TOKENS = 150
_JSON_SYSTEM = "Reply with a valid JSON object only, no prose."

COMMANDS = {
    "/params": "configure API params (max_tokens, stop, json) — toggle on/off",
    "/params off": "disable API params, back to raw mode",
    "/hint": "show prompt-constrained template to copy-paste",
    "/temp <q>": "run same question at temperature 0 / 0.7 / 1.2 / 2.0 (×3 each)",
    "/solve <q>": "run one task through 4 prompting techniques and compare",
    "/judge": "ask model to compare last /solve results and pick the best",
    "/debug": "toggle raw request JSON output (off by default)",
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


def print_request(model_id: str, messages: list[dict], **params) -> None:
    payload = build_payload(model_id, messages, **params)
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    syntax = Syntax(body, "json", theme="ansi_dark")
    console.print(Panel(syntax, title="REQUEST → API", expand=False))


def _print_solution(label: str, content: str, finish_reason: str, usage: object) -> int:
    console.print(f"\n[bold yellow]{label}[/]")
    console.print(Rule(style="dim"))
    console.print(content.strip())
    if usage:
        console.print(
            f"\n[dim]↑ {usage.prompt_tokens} · ↓ {usage.completion_tokens} · "
            f"finish: {finish_reason}[/]\n"
        )
        return usage.total_tokens
    console.print(f"\n[dim]finish: {finish_reason}[/]\n")
    return 0


def run_temp(
    client: OpenAI,
    model_id: str,
    question: str,
    *,
    temps: tuple[float, ...] = DEFAULT_TEMPS,
    repeats: int = DEFAULT_REPEATS,
    max_tokens: int = DEFAULT_TEMP_MAX_TOKENS,
    debug: bool = False,
) -> None:
    msgs = [{"role": "user", "content": question}]
    console.print(Panel(f"[bold]Temperature sweep[/]\n[dim]{question}[/]", expand=False))
    for temp in temps:
        for run in range(1, repeats + 1):
            label = f"temp={temp}  run {run}/{repeats}"
            if debug:
                print_request(model_id, msgs, temperature=temp, max_tokens=max_tokens)
            try:
                content, finish, usage = get_response(
                    client, model_id, msgs, temperature=temp, max_tokens=max_tokens
                )
                _print_solution(label, content, finish, usage)
            except Exception as e:
                console.print(f"[red]Error (temp={temp} run {run}):[/] {e}\n")


def run_solve(
    client: OpenAI, model_id: str, question: str, *, debug: bool = False
) -> list[tuple[str, str]]:
    console.print(Panel(f"[bold]Solve · 4 techniques[/]\n[dim]{question}[/]", expand=False))
    results: list[tuple[str, str]] = []
    total_tokens = 0

    try:
        msgs = direct(question)
        if debug:
            print_request(model_id, msgs)
        content, finish_reason, usage = get_response(client, model_id, msgs)
        total_tokens += _print_solution("1 · Direct", content, finish_reason, usage)
        results.append(("1 · Direct", content))
    except Exception as e:
        console.print(f"[red]Error (direct):[/] {e}\n")

    try:
        msgs = cot(question)
        if debug:
            print_request(model_id, msgs)
        content, finish_reason, usage = get_response(client, model_id, msgs)
        total_tokens += _print_solution("2 · Chain of Thought", content, finish_reason, usage)
        results.append(("2 · Chain of Thought", content))
    except Exception as e:
        console.print(f"[red]Error (cot):[/] {e}\n")

    try:
        lang = "ru" if is_russian(question) else "en"
        step1_msgs = [
            {"role": "user", "content": META_STEP1_TEMPLATE[lang].format(question=question)}
        ]
        if debug:
            print_request(model_id, step1_msgs)
        generated, _, _ = get_response(client, model_id, step1_msgs)

        step2_msgs = [{"role": "user", "content": generated}]
        if debug:
            print_request(model_id, step2_msgs)
        content, finish_reason, usage = get_response(client, model_id, step2_msgs)

        console.print("\n[bold yellow]3 · Meta-prompt[/] [dim](model wrote this prompt)[/]")
        console.print(Rule(style="dim"))
        console.print(f"[italic dim]{generated.strip()}[/]")
        console.print(Rule(style="dim"))
        total_tokens += _print_solution("3 · Meta-prompt → solution", content, finish_reason, usage)
        results.append(("3 · Meta-prompt", content))
    except Exception as e:
        console.print(f"[red]Error (meta):[/] {e}\n")

    try:
        msgs = experts(question)
        if debug:
            print_request(model_id, msgs)
        content, finish_reason, usage = get_response(client, model_id, msgs)
        total_tokens += _print_solution("4 · Experts panel", content, finish_reason, usage)
        results.append(("4 · Experts panel", content))
    except Exception as e:
        console.print(f"[red]Error (experts):[/] {e}\n")

    console.print(f"[dim]Total experiment cost: {total_tokens} tokens[/]\n")
    return results


def run_judge(
    client: OpenAI,
    model_id: str,
    question: str,
    solutions: list[tuple[str, str]],
    *,
    debug: bool = False,
) -> None:
    if not solutions:
        console.print("[red]No solutions to judge. Run /solve first.[/]\n")
        return

    solutions_text = "\n\n".join(f"[{label}]:\n{content}" for label, content in solutions)
    lang = "ru" if is_russian(question) else "en"
    judge_prompt = JUDGE_TEMPLATE[lang].format(question=question, solutions=solutions_text)
    msgs = [{"role": "user", "content": judge_prompt}]

    console.print(Panel("[bold]Judge[/] — comparing all solutions", expand=False))
    try:
        if debug:
            print_request(model_id, msgs)
        content, finish_reason, usage = get_response(client, model_id, msgs)
        console.print(content.strip())
        tokens = f"↑ {usage.prompt_tokens} · ↓ {usage.completion_tokens}" if usage else ""
        console.print(f"\n[dim]{tokens} · finish: {finish_reason}[/]\n")
    except Exception as e:
        console.print(f"[red]Error (judge):[/] {e}\n")


def chat_loop(provider_name: str) -> bool:
    client, model_id = get_client(provider_name)
    messages: list[dict[str, str]] = []
    api_params: dict = {}
    last_solutions: list[tuple[str, str]] = []
    last_question: str = ""
    debug_on: bool = False

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
                    "[dim]💡 Tip: /clear history before comparing for cleaner ↑ tokens.[/]"
                )
            api_params = ask_params()
            continue

        if user_input == "/hint":
            print_hint()
            continue

        if user_input == "/debug":
            debug_on = not debug_on
            state = "[green]ON[/]" if debug_on else "[dim]OFF[/]"
            console.print(f"Debug mode: {state}\n")
            continue

        if user_input == "/temp" or user_input.startswith("/temp "):
            question = user_input[len("/temp ") :].strip() if " " in user_input else ""
            if question:
                run_temp(client, model_id, question, debug=debug_on)
            else:
                console.print("[red]Usage:[/] /temp <your question>\n")
            continue

        if user_input == "/solve" or user_input.startswith("/solve "):
            question = user_input[len("/solve ") :].strip() if " " in user_input else ""
            if question:
                last_question = question
                last_solutions = run_solve(client, model_id, question, debug=debug_on)
            else:
                console.print("[red]Usage:[/] /solve <your task>\n")
            continue

        if user_input == "/judge":
            run_judge(client, model_id, last_question, last_solutions, debug=debug_on)
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

        # When json mode is on but the prompt has no "json" keyword, OpenAI/DeepSeek
        # reject the request (400). Inject a system instruction automatically.
        json_mode = "response_format" in api_params
        if json_mode and "json" not in user_input.lower():
            effective_messages = [{"role": "system", "content": _JSON_SYSTEM}] + messages
        else:
            effective_messages = messages

        if api_params:
            # non-streaming: get_response returns content + finish_reason + usage
            try:
                if debug_on:
                    print_request(model_id, effective_messages, **api_params)
                content, finish_reason, usage = get_response(
                    client,
                    model_id,
                    effective_messages,
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
            if debug_on:
                print_request(model_id, effective_messages)
            full_response: list[str] = []
            usage = None
            try:
                for chunk in stream_response(client, model_id, effective_messages):
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
