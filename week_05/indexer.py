from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from week_05.chunking import FixedSizeChunker, StructureChunker
from week_05.documents import load_documents
from week_05.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    approx_token_count,
    embed_with_retry,
)
from week_05.index_store import IndexStore
from week_05.models import Chunk, ChunkingStats, EmbeddedChunk, IndexResult, IndexRun

MAX_BATCH_CHUNKS = 100
MAX_BATCH_CHARS = 200_000


@dataclass(frozen=True)
class PipelineOutput:
    result: IndexResult
    warnings: list[str]
    stats: ChunkingStats


def _chunker_for(strategy: str):
    if strategy == "fixed":
        return FixedSizeChunker()
    if strategy == "structure":
        return StructureChunker()
    raise ValueError(f"Unsupported strategy: {strategy}")


def _l2_norm(vector: list[float]) -> float:
    if not vector:
        return 0.0
    return math.sqrt(sum(x * x for x in vector))


def _batched(chunks: list[Chunk], max_items: int, max_chars: int) -> list[list[Chunk]]:
    batches: list[list[Chunk]] = []
    current: list[Chunk] = []
    current_chars = 0
    for chunk in chunks:
        c_len = len(chunk.text)
        if current and (len(current) >= max_items or current_chars + c_len > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(chunk)
        current_chars += c_len
    if current:
        batches.append(current)
    return batches


def _stats_for(strategy: str, chunks: list[Chunk]) -> ChunkingStats:
    if not chunks:
        return ChunkingStats(
            strategy=strategy,
            document_count=0,
            chunk_count=0,
            min_chunk_chars=0,
            max_chunk_chars=0,
            avg_chunk_chars=0.0,
            source_count=0,
        )
    lengths = [len(c.text) for c in chunks]
    sources = {c.source for c in chunks}
    return ChunkingStats(
        strategy=strategy,
        document_count=len({c.source for c in chunks}),
        chunk_count=len(chunks),
        min_chunk_chars=min(lengths),
        max_chunk_chars=max(lengths),
        avg_chunk_chars=sum(lengths) / len(lengths),
        source_count=len(sources),
    )


def _run_id(source_root: str, strategy: str) -> str:
    now = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S%f")
    salt = uuid4().hex[:8]
    digest = hashlib.sha256(f"{source_root}:{strategy}:{now}:{salt}".encode()).hexdigest()[:8]
    return f"{strategy}-{now}-{digest}"


def index_documents(
    source: Path,
    strategy: str,
    db_path: Path,
    *,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    limit: int | None = None,
    dry_run: bool = False,
    provider: EmbeddingProvider | None = None,
) -> PipelineOutput:
    source = source.resolve()
    documents, warnings = load_documents(source)

    chunker = _chunker_for(strategy)
    chunks: list[Chunk] = []
    for doc in documents:
        chunks.extend(chunker.chunk(doc))

    if limit is not None and limit > 0:
        chunks = chunks[:limit]

    chunk_stats = _stats_for(strategy, chunks)
    approx_chars = sum(len(c.text) for c in chunks)
    approx_tokens = sum(approx_token_count(c.text) for c in chunks)

    run_id = _run_id(str(source), strategy)
    now = datetime.now(tz=UTC).isoformat()

    if dry_run:
        result = IndexResult(
            strategy=strategy,
            run_id=run_id,
            source_root=str(source),
            document_count=len(documents),
            chunk_count=len(chunks),
            missing_embedding_count=0,
            cache_hits=0,
            api_calls=0,
            avg_chunk_chars=chunk_stats.avg_chunk_chars,
            approx_chars=approx_chars,
            db_path=db_path.resolve(),
        )
        return PipelineOutput(result=result, warnings=warnings, stats=chunk_stats)

    store = IndexStore(db_path.resolve())
    store.init()
    emb_provider = provider or OpenAIEmbeddingProvider(model=embedding_model)
    embedded_rows: list[EmbeddedChunk] = []
    cache_hits = 0
    api_calls = 0
    missing = 0

    uncached: list[Chunk] = []
    for chunk in chunks:
        cached = store.cache_get(chunk.content_hash, emb_provider.model)
        if cached is not None:
            cache_hits += 1
            embedded_rows.append(
                EmbeddedChunk(
                    chunk=chunk,
                    embedding=cached,
                    embedding_dim=len(cached),
                    embedding_norm=_l2_norm(cached),
                    from_cache=True,
                )
            )
        else:
            uncached.append(chunk)

    for batch in _batched(uncached, MAX_BATCH_CHUNKS, MAX_BATCH_CHARS):
        texts = [chunk.text for chunk in batch]
        try:
            vectors = embed_with_retry(emb_provider, texts, retries=1, base_backoff_s=0.8)
            api_calls += 1
        except Exception as exc:
            missing += len(batch)
            warnings.append(f"Embedding batch failed ({len(batch)} chunks): {exc}")
            for chunk in batch:
                embedded_rows.append(
                    EmbeddedChunk(
                        chunk=chunk,
                        embedding=None,
                        embedding_dim=0,
                        embedding_norm=0.0,
                        from_cache=False,
                    )
                )
            continue

        for chunk, vector in zip(batch, vectors, strict=False):
            store.cache_put(chunk.content_hash, emb_provider.model, vector)
            embedded_rows.append(
                EmbeddedChunk(
                    chunk=chunk,
                    embedding=vector,
                    embedding_dim=len(vector),
                    embedding_norm=_l2_norm(vector),
                    from_cache=False,
                )
            )

    run = IndexRun(
        id=run_id,
        strategy=strategy,
        embedding_model=emb_provider.model,
        created_at=now,
        source_root=str(source),
        document_count=len(documents),
        chunk_count=len(chunks),
        missing_embedding_count=missing,
        metadata={
            "approx_tokens": str(approx_tokens),
            "warnings_count": str(len(warnings)),
            "max_batch_chunks": str(MAX_BATCH_CHUNKS),
            "max_batch_chars": str(MAX_BATCH_CHARS),
        },
    )
    store.upsert_run(run)
    store.save_chunks(run_id, embedded_rows)

    result = IndexResult(
        strategy=strategy,
        run_id=run_id,
        source_root=str(source),
        document_count=len(documents),
        chunk_count=len(chunks),
        missing_embedding_count=missing,
        cache_hits=cache_hits,
        api_calls=api_calls,
        avg_chunk_chars=chunk_stats.avg_chunk_chars,
        approx_chars=approx_chars,
        db_path=db_path.resolve(),
    )
    return PipelineOutput(result=result, warnings=warnings, stats=chunk_stats)
