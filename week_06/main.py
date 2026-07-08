from __future__ import annotations

import argparse

from shared.config import PROVIDERS
from week_06.local_client import OllamaClient, OllamaClientError

EXIT_WORDS = {"exit", "quit", "выход"}


def local_providers() -> list[str]:
    return [name for name, provider in PROVIDERS.items() if provider.api_key_env is None]


def parse_args() -> argparse.Namespace:
    providers = local_providers()
    parser = argparse.ArgumentParser(description="Day 26 local LLM demo")
    parser.add_argument(
        "--provider",
        default=providers[0],
        choices=providers,
        help="Local provider name from shared/config.py PROVIDERS",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="One-shot prompt. If omitted, starts an interactive ask loop.",
    )
    return parser.parse_args()


def ask_once(client: OllamaClient, prompt: str) -> None:
    try:
        result = client.generate(prompt)
    except OllamaClientError as exc:
        print(f"error={exc}")
        return
    print(f"latency_s={result.latency_seconds:.2f} finish_reason={result.finish_reason}")
    print(result.text)
    print()


def repl(client: OllamaClient) -> None:
    print("Interactive ask mode. Type a prompt, empty line or 'exit'/'quit' to stop.")
    print()
    while True:
        try:
            prompt = input("ask> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not prompt or prompt.lower() in EXIT_WORDS:
            break
        ask_once(client, prompt)


def run() -> int:
    args = parse_args()

    try:
        client = OllamaClient(provider_name=args.provider)
    except OllamaClientError as exc:
        print(f"error={exc}")
        return 1

    print("Day 26 local LLM demo")
    print(f"provider={client.provider_name} model={client.model_id}")
    print()

    if args.prompt is not None:
        ask_once(client, args.prompt)
    else:
        repl(client)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
