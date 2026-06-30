from __future__ import annotations

import os
import time
from typing import Protocol

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


class EmbeddingProvider(Protocol):
    model: str

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider:
    def __init__(self, model: str = DEFAULT_EMBEDDING_MODEL) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise OSError("Missing env var: OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]


def approx_token_count(text: str) -> int:
    # Coarse estimate suitable for cost previews.
    return max(1, len(text) // 4)


def embed_with_retry(
    provider: EmbeddingProvider, texts: list[str], *, retries: int = 1, base_backoff_s: float = 0.8
) -> list[list[float]]:
    attempt = 0
    while True:
        try:
            return provider.embed_texts(texts)
        except Exception:
            if attempt >= retries:
                raise
            sleep_s = base_backoff_s * (2**attempt)
            time.sleep(sleep_s)
            attempt += 1
