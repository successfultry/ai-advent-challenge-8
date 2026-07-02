from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from week_05.index_store import IndexStore
from week_05.models import Chunk, EmbeddedChunk, IndexRun
from week_05.retrieval import retrieve_chunks


class FakeEmbeddingProvider:
    def __init__(self, model: str, vector: list[float]) -> None:
        self.model = model
        self._vector = vector

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [list(self._vector) for _ in texts]


def _chunk(chunk_id: str, text: str, strategy: str = "structure") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        source="week_05/corpus/lecture-05-notes.md",
        title="lecture-05-notes",
        section="heading:demo",
        text=text,
        strategy=strategy,
        start_char=0,
        end_char=len(text),
        content_hash=f"h-{chunk_id}",
        extension=".md",
        language="markdown",
        metadata={},
    )


def _run(run_id: str, strategy: str, source_root: str, created_at: str) -> IndexRun:
    return IndexRun(
        id=run_id,
        strategy=strategy,
        embedding_model="embed-model-a",
        created_at=created_at,
        source_root=source_root,
        document_count=1,
        chunk_count=1,
        missing_embedding_count=0,
        metadata={},
    )


def test_retrieval_uses_latest_run_only(tmp_path: Path) -> None:
    db = tmp_path / "idx.sqlite"
    source_root = (tmp_path / "corpus").resolve()
    source_root.mkdir(parents=True, exist_ok=True)

    store = IndexStore(db)
    store.init()
    store.upsert_run(_run("old-run", "structure", str(source_root), "2026-01-01T00:00:00+00:00"))
    store.upsert_run(_run("new-run", "structure", str(source_root), "2026-01-02T00:00:00+00:00"))

    old_row = EmbeddedChunk(
        chunk=_chunk("old-chunk", "old text"),
        embedding=[0.1, 0.1],
        embedding_dim=2,
        embedding_norm=0.2,
        from_cache=False,
    )
    new_row = EmbeddedChunk(
        chunk=_chunk("new-chunk", "new text"),
        embedding=[0.9, 0.9],
        embedding_dim=2,
        embedding_norm=1.2,
        from_cache=False,
    )
    store.save_chunks("old-run", [old_row])
    store.save_chunks("new-run", [new_row])

    out = retrieve_chunks(
        db_path=db,
        source_root=source_root,
        question="test",
        strategy="structure",
        top_k=5,
        provider=FakeEmbeddingProvider("embed-model-a", [1.0, 1.0]),
    )
    assert out.run_id == "new-run"
    assert out.retrieved_count == 1
    assert out.chunks[0].chunk_id == "new-chunk"


def test_retrieval_requires_existing_run(tmp_path: Path) -> None:
    db = tmp_path / "idx.sqlite"
    source_root = (tmp_path / "corpus").resolve()
    source_root.mkdir(parents=True, exist_ok=True)
    store = IndexStore(db)
    store.init()

    with pytest.raises(ValueError, match="Run `index` first"):
        retrieve_chunks(
            db_path=db,
            source_root=source_root,
            question="hello",
            strategy="structure",
            provider=FakeEmbeddingProvider("embed-model-a", [1.0, 1.0]),
        )


def test_retrieval_rejects_empty_question(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Question must not be empty"):
        retrieve_chunks(
            db_path=tmp_path / "idx.sqlite",
            source_root=tmp_path,
            question="  ",
            provider=FakeEmbeddingProvider("embed-model-a", [1.0]),
        )


def test_retrieval_raises_on_dimension_mismatch(tmp_path: Path) -> None:
    db = tmp_path / "idx.sqlite"
    source_root = tmp_path.resolve()
    store = IndexStore(db)
    store.init()
    run = IndexRun(
        id="run-x",
        strategy="structure",
        embedding_model="embed-model-a",
        created_at=datetime.now(tz=UTC).isoformat(),
        source_root=str(source_root),
        document_count=1,
        chunk_count=1,
        missing_embedding_count=0,
        metadata={},
    )
    store.upsert_run(run)
    store.save_chunks(
        "run-x",
        [
            EmbeddedChunk(
                chunk=_chunk("chunk-x", "hello"),
                embedding=[1.0, 2.0, 3.0],
                embedding_dim=3,
                embedding_norm=3.7,
                from_cache=False,
            )
        ],
    )

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        retrieve_chunks(
            db_path=db,
            source_root=source_root,
            question="hello",
            strategy="structure",
            provider=FakeEmbeddingProvider("embed-model-a", [1.0, 2.0]),
        )


def test_retrieval_top_k_zero_returns_empty(tmp_path: Path) -> None:
    db = tmp_path / "idx.sqlite"
    source_root = tmp_path.resolve()
    store = IndexStore(db)
    store.init()
    store.upsert_run(
        IndexRun(
            id="run-z",
            strategy="structure",
            embedding_model="embed-model-a",
            created_at=datetime.now(tz=UTC).isoformat(),
            source_root=str(source_root),
            document_count=0,
            chunk_count=0,
            missing_embedding_count=0,
            metadata={},
        )
    )
    out = retrieve_chunks(
        db_path=db,
        source_root=source_root,
        question="q",
        strategy="structure",
        top_k=0,
        provider=FakeEmbeddingProvider("embed-model-a", [1.0]),
    )
    assert out.run_id == "run-z"
    assert out.chunks == []


def test_retrieval_threshold_and_two_stage_counts(tmp_path: Path) -> None:
    db = tmp_path / "idx.sqlite"
    source_root = tmp_path.resolve()
    store = IndexStore(db)
    store.init()
    store.upsert_run(
        IndexRun(
            id="run-two-stage",
            strategy="structure",
            embedding_model="embed-model-a",
            created_at=datetime.now(tz=UTC).isoformat(),
            source_root=str(source_root),
            document_count=1,
            chunk_count=3,
            missing_embedding_count=0,
            metadata={},
        )
    )
    store.save_chunks(
        "run-two-stage",
        [
            EmbeddedChunk(
                chunk=_chunk("c1", "one"),
                embedding=[1.0, 0.0],
                embedding_dim=2,
                embedding_norm=1.0,
                from_cache=False,
            ),
            EmbeddedChunk(
                chunk=_chunk("c2", "two"),
                embedding=[0.8, 0.2],
                embedding_dim=2,
                embedding_norm=0.8246,
                from_cache=False,
            ),
            EmbeddedChunk(
                chunk=_chunk("c3", "three"),
                embedding=[0.1, 0.9],
                embedding_dim=2,
                embedding_norm=0.9055,
                from_cache=False,
            ),
        ],
    )

    out = retrieve_chunks(
        db_path=db,
        source_root=source_root,
        question="demo",
        strategy="structure",
        top_k=1,
        top_k_before=3,
        min_similarity=0.7,
        provider=FakeEmbeddingProvider("embed-model-a", [1.0, 0.0]),
    )
    assert out.retrieved_before == 3
    assert out.retrieved_after_threshold == 2
    assert out.retrieved_count == 1
    assert out.chunks[0].chunk_id == "c1"
