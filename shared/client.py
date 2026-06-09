from __future__ import annotations

import os
import time
from collections.abc import Iterator

from dotenv import load_dotenv
from openai import OpenAI

from shared.config import PROVIDERS

load_dotenv()


def available_providers() -> list[str]:
    return [name for name, (_, _, env_var) in PROVIDERS.items() if os.environ.get(env_var)]


def get_client(provider_name: str) -> tuple[OpenAI, str]:
    base_url, model_id, env_var = PROVIDERS[provider_name]
    api_key = os.environ.get(env_var)
    if not api_key:
        raise OSError(f"Missing env var: {env_var}")
    return OpenAI(base_url=base_url, api_key=api_key), model_id


def build_payload(
    model_id: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
    stop: list[str] | None = None,
    response_format: dict | None = None,
    temperature: float | None = None,
) -> dict:
    params: dict = {"model": model_id, "messages": messages}
    if max_tokens is not None:
        params["max_tokens"] = max_tokens
    if stop is not None:
        params["stop"] = stop
    if response_format is not None:
        params["response_format"] = response_format
    if temperature is not None:
        params["temperature"] = temperature
    return params


def get_response(
    client: OpenAI,
    model_id: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
    stop: list[str] | None = None,
    response_format: dict | None = None,
    temperature: float | None = None,
) -> tuple[str, str, object]:
    resp = client.chat.completions.create(
        model=model_id,
        messages=messages,
        max_tokens=max_tokens,
        stop=stop,
        response_format=response_format,
        temperature=temperature,
    )
    choice = resp.choices[0]
    return choice.message.content or "", choice.finish_reason or "unknown", resp.usage


def timed_response(
    client: OpenAI,
    model_id: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> tuple[str, str, object, float]:
    t0 = time.perf_counter()
    content, reason, usage = get_response(
        client, model_id, messages, max_tokens=max_tokens, temperature=temperature
    )
    return content, reason, usage, time.perf_counter() - t0


def stream_response(
    client: OpenAI,
    model_id: str,
    messages: list[dict[str, str]],
) -> Iterator[str | dict]:
    stream = client.chat.completions.create(
        model=model_id,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
        if chunk.usage:
            yield {"usage": chunk.usage}
