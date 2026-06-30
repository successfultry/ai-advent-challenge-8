from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from week_05.index_store import IndexStore
from week_05.indexer import index_documents
from week_05.models import Chunk, EmbeddedChunk, IndexRun


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.model = "fake-embedding-model"
        self.calls = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(len(text)), 1.0, 0.5] for text in texts]


def _chunk(i: int) -> Chunk:
    text = f"chunk-{i}"
    return Chunk(
        chunk_id=f"id-{i}",
        source="s.txt",
        title="s",
        section="full_document",
        text=text,
        strategy="fixed",
        start_char=i * 5,
        end_char=(i + 1) * 5,
        content_hash=f"h-{i}",
        extension=".txt",
        language="text",
        metadata={},
    )


def test_index_store_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "idx.sqlite"
    store = IndexStore(db)
    store.init()

    run = IndexRun(
        id="run-1",
        strategy="fixed",
        embedding_model="model-x",
        created_at=datetime.now(tz=UTC).isoformat(),
        source_root="/tmp/source",
        document_count=1,
        chunk_count=3,
        missing_embedding_count=0,
        metadata={"k": "v"},
    )
    store.upsert_run(run)

    rows = [
        EmbeddedChunk(
            chunk=_chunk(1),
            embedding=[1.0, 2.0],
            embedding_dim=2,
            embedding_norm=2.236,
            from_cache=False,
        ),
        EmbeddedChunk(
            chunk=_chunk(2),
            embedding=[3.0, 4.0],
            embedding_dim=2,
            embedding_norm=5.0,
            from_cache=False,
        ),
        EmbeddedChunk(
            chunk=_chunk(3),
            embedding=None,
            embedding_dim=0,
            embedding_norm=0.0,
            from_cache=False,
        ),
    ]
    store.save_chunks(run.id, rows)

    latest = store.latest_run("fixed", "/tmp/source")
    assert latest is not None
    assert latest.id == "run-1"
    assert latest.chunk_count == 3
    assert len(store.run_chunks("run-1")) == 3
    assert store.chunks_per_source("run-1") == {"s.txt": 3}


def test_embedding_cache_reduces_api_calls(tmp_path: Path) -> None:
    source = tmp_path / "docs"
    source.mkdir(parents=True, exist_ok=True)
    (source / "a.txt").write_text("same content\n" * 40, encoding="utf-8")
    db = tmp_path / "cache.sqlite"

    provider = FakeEmbeddingProvider()
    first = index_documents(
        source=source,
        strategy="fixed",
        db_path=db,
        provider=provider,
        embedding_model=provider.model,
        limit=5,
    )
    second = index_documents(
        source=source,
        strategy="fixed",
        db_path=db,
        provider=provider,
        embedding_model=provider.model,
        limit=5,
    )

    assert first.result.api_calls >= 1
    assert second.result.api_calls == 0
    assert second.result.cache_hits == second.result.chunk_count


def test_pdf_loader_error_path_is_graceful(tmp_path: Path) -> None:
    source = tmp_path / "docs"
    source.mkdir(parents=True, exist_ok=True)
    (source / "broken.pdf").write_bytes(b"this is not a real pdf")
    db = tmp_path / "broken.sqlite"

    out = index_documents(source=source, strategy="fixed", db_path=db, dry_run=True)
    assert out.result.document_count == 0
    assert any("Skipping unreadable file" in warning for warning in out.warnings)
    assert not db.exists()
