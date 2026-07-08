from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAIError

from shared.client import get_client, timed_response


class OllamaClientError(RuntimeError):
    pass


@dataclass
class OllamaResponse:
    text: str
    latency_seconds: float
    finish_reason: str


class OllamaClient:
    def __init__(self, provider_name: str) -> None:
        try:
            client, model_id = get_client(provider_name)
        except OSError as exc:
            raise OllamaClientError(str(exc)) from exc
        self.provider_name = provider_name
        self.model_id = model_id
        self._client = client

    def generate(self, prompt: str) -> OllamaResponse:
        messages = [{"role": "user", "content": prompt}]
        try:
            content, finish_reason, _usage, latency = timed_response(
                self._client, self.model_id, messages
            )
        except OpenAIError as exc:
            raise OllamaClientError(
                f"Ollama request failed (is `ollama serve` running?): {exc}"
            ) from exc

        text = content.strip()
        if not text:
            raise OllamaClientError("Ollama returned empty response text")

        return OllamaResponse(text=text, latency_seconds=latency, finish_reason=finish_reason)
