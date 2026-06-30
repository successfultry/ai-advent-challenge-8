from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from week_05.models import EmbeddedChunk, IndexRun

SCHEMA_VERSION = 1


class IndexStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    schema_version INTEGER NOT NULL
                )
                """
            )
            count_row = conn.execute("SELECT COUNT(*) AS c FROM meta").fetchone()
            if count_row and int(count_row["c"]) == 0:
                conn.execute("INSERT INTO meta(schema_version) VALUES (?)", (SCHEMA_VERSION,))

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS index_runs (
                    id TEXT PRIMARY KEY,
                    strategy TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    source_root TEXT NOT NULL,
                    document_count INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    missing_embedding_count INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    section TEXT NOT NULL,
                    text TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    start_char INTEGER NOT NULL,
                    end_char INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    embedding_json TEXT,
                    embedding_dim INTEGER NOT NULL,
                    embedding_norm REAL NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES index_runs(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    text_hash TEXT NOT NULL,
                    model TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    PRIMARY KEY(text_hash, model)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_run_id ON chunks(run_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source)"
            )
            conn.commit()

    def upsert_run(self, run: IndexRun) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO index_runs(
                    id, strategy, embedding_model, created_at, source_root,
                    document_count, chunk_count, missing_embedding_count, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    strategy=excluded.strategy,
                    embedding_model=excluded.embedding_model,
                    created_at=excluded.created_at,
                    source_root=excluded.source_root,
                    document_count=excluded.document_count,
                    chunk_count=excluded.chunk_count,
                    missing_embedding_count=excluded.missing_embedding_count,
                    metadata_json=excluded.metadata_json
                """,
                (
                    run.id,
                    run.strategy,
                    run.embedding_model,
                    run.created_at,
                    run.source_root,
                    run.document_count,
                    run.chunk_count,
                    run.missing_embedding_count,
                    json.dumps(run.metadata, ensure_ascii=False),
                ),
            )
            conn.commit()

    def cache_get(self, text_hash: str, model: str) -> list[float] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT embedding_json
                FROM embedding_cache
                WHERE text_hash = ? AND model = ?
                """,
                (text_hash, model),
            ).fetchone()
        if not row:
            return None
        return list(json.loads(str(row["embedding_json"])))

    def cache_put(self, text_hash: str, model: str, embedding: list[float]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO embedding_cache(text_hash, model, embedding_json, dim)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(text_hash, model) DO UPDATE SET
                    embedding_json = excluded.embedding_json,
                    dim = excluded.dim
                """,
                (text_hash, model, json.dumps(embedding), len(embedding)),
            )
            conn.commit()

    def save_chunks(self, run_id: str, rows: list[EmbeddedChunk]) -> None:
        with self._connect() as conn:
            payload = []
            for row in rows:
                embedding_json = json.dumps(row.embedding) if row.embedding is not None else None
                payload.append(
                    (
                        f"{run_id}:{row.chunk.chunk_id}",
                        run_id,
                        row.chunk.chunk_id,
                        row.chunk.source,
                        row.chunk.title,
                        row.chunk.section,
                        row.chunk.text,
                        row.chunk.strategy,
                        row.chunk.start_char,
                        row.chunk.end_char,
                        row.chunk.content_hash,
                        json.dumps(
                            {
                                **row.chunk.metadata,
                                "extension": row.chunk.extension,
                                "language": row.chunk.language,
                            },
                            ensure_ascii=False,
                        ),
                        embedding_json,
                        row.embedding_dim,
                        row.embedding_norm,
                    )
                )
            conn.executemany(
                """
                INSERT INTO chunks(
                    id, run_id, chunk_id, source, title, section, text, strategy,
                    start_char, end_char, content_hash, metadata_json,
                    embedding_json, embedding_dim, embedding_norm
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source = excluded.source,
                    title = excluded.title,
                    section = excluded.section,
                    text = excluded.text,
                    strategy = excluded.strategy,
                    start_char = excluded.start_char,
                    end_char = excluded.end_char,
                    content_hash = excluded.content_hash,
                    metadata_json = excluded.metadata_json,
                    embedding_json = excluded.embedding_json,
                    embedding_dim = excluded.embedding_dim,
                    embedding_norm = excluded.embedding_norm
                """,
                payload,
            )
            conn.commit()

    def latest_run(self, strategy: str, source_root: str) -> IndexRun | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM index_runs
                WHERE strategy = ? AND source_root = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (strategy, source_root),
            ).fetchone()
        if not row:
            return None
        return IndexRun(
            id=str(row["id"]),
            strategy=str(row["strategy"]),
            embedding_model=str(row["embedding_model"]),
            created_at=str(row["created_at"]),
            source_root=str(row["source_root"]),
            document_count=int(row["document_count"]),
            chunk_count=int(row["chunk_count"]),
            missing_embedding_count=int(row["missing_embedding_count"]),
            metadata=json.loads(str(row["metadata_json"])),
        )

    def run_chunks(self, run_id: str) -> list[sqlite3.Row]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM chunks
                WHERE run_id = ?
                ORDER BY source, start_char
                """,
                (run_id,),
            ).fetchall()
        return rows

    def chunks_per_source(self, run_id: str) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source, COUNT(*) AS cnt
                FROM chunks
                WHERE run_id = ?
                GROUP BY source
                ORDER BY source
                """,
                (run_id,),
            ).fetchall()
        return {str(row["source"]): int(row["cnt"]) for row in rows}

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            run_count = conn.execute("SELECT COUNT(*) AS c FROM index_runs").fetchone()
            chunk_count = conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()
            cache_count = conn.execute("SELECT COUNT(*) AS c FROM embedding_cache").fetchone()
        return {
            "runs": int(run_count["c"]) if run_count else 0,
            "chunks": int(chunk_count["c"]) if chunk_count else 0,
            "cache_entries": int(cache_count["c"]) if cache_count else 0,
        }
