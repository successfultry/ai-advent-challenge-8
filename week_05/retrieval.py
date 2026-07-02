from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from week_05.embeddings import EmbeddingProvider, OpenAIEmbeddingProvider
from week_05.index_store import IndexStore


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    source: str
    title: str
    section: str
    strategy: str
    score: float
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class RetrievalResult:
    chunks: list[RetrievedChunk]
    run_id: str
    embedding_model_used: str
    retrieved_count: int
    avg_score: float
    retrieved_before: int = 0
    retrieved_after_threshold: int = 0
    rewritten_query: str | None = None


def _l2_norm(vector: list[float]) -> float:
    if not vector:
        return 0.0
    return math.sqrt(sum(value * value for value in vector))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    denom = _l2_norm(a) * _l2_norm(b)
    if denom <= 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / denom


@dataclass(frozen=True)
class _ScoredChunk:
    chunk: RetrievedChunk
    embedding: list[float]


def _mmr_select(
    candidates: list[_ScoredChunk],
    *,
    top_k: int,
    lambda_relevance: float = 0.85,
) -> list[_ScoredChunk]:
    if top_k <= 0 or not candidates:
        return []

    selected: list[_ScoredChunk] = []
    remaining = list(candidates)
    while remaining and len(selected) < top_k:
        best_idx = -1
        best_score = float("-inf")
        for idx, candidate in enumerate(remaining):
            relevance = candidate.chunk.score
            if not selected:
                mmr_score = relevance
            else:
                max_sim = max(
                    _cosine_similarity(candidate.embedding, item.embedding) for item in selected
                )
                mmr_score = lambda_relevance * relevance - (1.0 - lambda_relevance) * max_sim
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx
        selected.append(remaining.pop(best_idx))
    return selected


def retrieve_chunks(
    db_path: Path,
    source_root: Path,
    question: str,
    *,
    strategy: str = "structure",
    top_k: int = 5,
    top_k_before: int | None = None,
    min_similarity: float = -1.0,
    use_mmr: bool = False,
    rewritten_query: str | None = None,
    provider: EmbeddingProvider | None = None,
) -> RetrievalResult:
    normalized_question = question.strip()
    if not normalized_question:
        raise ValueError("Question must not be empty.")

    source_root = source_root.resolve()
    store = IndexStore(db_path.resolve())
    store.init()

    latest = store.latest_run(strategy, str(source_root))
    if latest is None:
        raise ValueError(
            f"No index run found for strategy={strategy} source={source_root}. "
            "Run `index` first for this strategy/source."
        )

    if top_k <= 0:
        return RetrievalResult(
            chunks=[],
            run_id=latest.id,
            embedding_model_used=latest.embedding_model,
            retrieved_before=0,
            retrieved_after_threshold=0,
            retrieved_count=0,
            avg_score=0.0,
            rewritten_query=rewritten_query,
        )

    stage_top_k = top_k if top_k_before is None else max(0, top_k_before)
    if stage_top_k <= 0:
        return RetrievalResult(
            chunks=[],
            run_id=latest.id,
            embedding_model_used=latest.embedding_model,
            retrieved_before=0,
            retrieved_after_threshold=0,
            retrieved_count=0,
            avg_score=0.0,
            rewritten_query=rewritten_query,
        )

    emb_provider = provider or OpenAIEmbeddingProvider(model=latest.embedding_model)
    if emb_provider.model != latest.embedding_model:
        raise ValueError(
            "Embedding model mismatch: retrieval provider model "
            f"({emb_provider.model}) differs from indexed model ({latest.embedding_model})."
        )

    query_vector = emb_provider.embed_texts([normalized_question])[0]
    query_dim = len(query_vector)

    rows = store.run_chunks(latest.id)
    scored: list[_ScoredChunk] = []
    for row in rows:
        embedding_raw = row["embedding_json"]
        if embedding_raw is None:
            continue
        chunk_dim = int(row["embedding_dim"])
        if chunk_dim != query_dim:
            raise ValueError(
                f"Embedding dimension mismatch: query_dim={query_dim}, chunk_dim={chunk_dim}. "
                "Rebuild index with the same embedding model."
            )
        chunk_embedding = list(json.loads(str(embedding_raw)))
        if len(chunk_embedding) != query_dim:
            raise ValueError(
                "Embedding dimension mismatch in stored chunk payload. "
                "Rebuild index with the same embedding model."
            )
        score = _cosine_similarity(query_vector, chunk_embedding)
        scored.append(
            _ScoredChunk(
                chunk=RetrievedChunk(
                    chunk_id=str(row["chunk_id"]),
                    source=str(row["source"]),
                    title=str(row["title"]),
                    section=str(row["section"]),
                    strategy=str(row["strategy"]),
                    score=score,
                    text=str(row["text"]),
                    start_char=int(row["start_char"]),
                    end_char=int(row["end_char"]),
                ),
                embedding=chunk_embedding,
            )
        )

    scored.sort(key=lambda item: item.chunk.score, reverse=True)
    before = scored[:stage_top_k]
    filtered = [item for item in before if item.chunk.score >= min_similarity]
    if use_mmr:
        final_items = _mmr_select(filtered, top_k=top_k)
    else:
        final_items = filtered[:top_k]

    selected = [item.chunk for item in final_items]
    avg_score = sum(item.score for item in selected) / len(selected) if selected else 0.0
    return RetrievalResult(
        chunks=selected,
        run_id=latest.id,
        embedding_model_used=latest.embedding_model,
        retrieved_before=len(before),
        retrieved_after_threshold=len(filtered),
        retrieved_count=len(selected),
        avg_score=avg_score,
        rewritten_query=rewritten_query,
    )
