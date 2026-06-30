from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Document:
    source: str
    title: str
    content: str
    extension: str
    language: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source: str
    title: str
    section: str
    text: str
    strategy: str
    start_char: int
    end_char: int
    content_hash: str
    extension: str
    language: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EmbeddedChunk:
    chunk: Chunk
    embedding: list[float] | None
    embedding_dim: int
    embedding_norm: float
    from_cache: bool


@dataclass(frozen=True)
class IndexRun:
    id: str
    strategy: str
    embedding_model: str
    created_at: str
    source_root: str
    document_count: int
    chunk_count: int
    missing_embedding_count: int
    metadata: dict[str, str]


@dataclass(frozen=True)
class IndexResult:
    strategy: str
    run_id: str
    source_root: str
    document_count: int
    chunk_count: int
    missing_embedding_count: int
    cache_hits: int
    api_calls: int
    avg_chunk_chars: float
    approx_chars: int
    db_path: Path


@dataclass(frozen=True)
class ChunkingStats:
    strategy: str
    document_count: int
    chunk_count: int
    min_chunk_chars: int
    max_chunk_chars: int
    avg_chunk_chars: float
    source_count: int
