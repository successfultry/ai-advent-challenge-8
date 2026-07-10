from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from shared.config import PROVIDERS

DEFAULT_TIMEOUT_SECONDS = 300.0


class OllamaClientError(RuntimeError):
    pass


@dataclass
class OllamaResponse:
    text: str
    latency_seconds: float
    finish_reason: str
    tokens_out: int | None = None
    prompt_tokens: int | None = None
    tokens_per_sec: float | None = None
    load_seconds: float | None = None


def _native_chat_url(openai_compat_base_url: str) -> str:
    return f"{openai_compat_base_url.removesuffix('/v1').rstrip('/')}/api/chat"


class OllamaClient:
    def __init__(
        self,
        provider_name: str,
        *,
        model_override: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if provider_name not in PROVIDERS:
            raise OllamaClientError(f"Unknown provider: {provider_name}")
        provider = PROVIDERS[provider_name]
        if provider.api_key_env is not None:
            raise OllamaClientError(f"{provider_name} is not a local (keyless) provider")
        self.provider_name = provider_name
        self.model_id = model_override or provider.model_id
        self._url = _native_chat_url(provider.base_url)
        self._timeout = timeout

    def generate(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        context_window: int | None = None,
    ) -> OllamaResponse:
        options: dict = {}
        if temperature is not None:
            options["temperature"] = temperature
        if top_p is not None:
            options["top_p"] = top_p
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if context_window is not None:
            options["num_ctx"] = context_window

        payload: dict = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        if options:
            payload["options"] = options

        request = urllib.request.Request(
            self._url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                raw = resp.read()
            latency = time.perf_counter() - t0
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OllamaClientError(
                f"Ollama request failed (model={self.model_id}): HTTP {exc.code} {detail}"
            ) from exc
        except TimeoutError as exc:
            raise OllamaClientError(
                f"Ollama request timed out after {self._timeout:.0f}s "
                f"(model={self.model_id}); cold model load + long CPU generation "
                "can exceed this, retry or raise timeout"
            ) from exc
        except OSError as exc:
            raise OllamaClientError(
                f"Ollama request failed (is `ollama serve` running?): {exc}"
            ) from exc

        data = json.loads(raw.decode("utf-8"))
        text = (data.get("message", {}).get("content") or "").strip()
        if not text:
            raise OllamaClientError("Ollama returned empty response text")

        tokens_out = data.get("eval_count")
        prompt_tokens = data.get("prompt_eval_count")
        eval_duration_ns = data.get("eval_duration")
        load_duration_ns = data.get("load_duration")

        tokens_per_sec = None
        if tokens_out and eval_duration_ns:
            tokens_per_sec = tokens_out / (eval_duration_ns / 1_000_000_000)

        return OllamaResponse(
            text=text,
            latency_seconds=latency,
            finish_reason="stop" if data.get("done") else "unknown",
            tokens_out=tokens_out,
            prompt_tokens=prompt_tokens,
            tokens_per_sec=tokens_per_sec,
            load_seconds=(load_duration_ns / 1_000_000_000) if load_duration_ns else None,
        )
