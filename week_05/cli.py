from __future__ import annotations

import argparse
import json
from pathlib import Path

from week_05.embeddings import DEFAULT_EMBEDDING_MODEL
from week_05.index_store import IndexStore
from week_05.indexer import PipelineOutput, index_documents

DEFAULT_DB_PATH = Path("data/week_05/rag_index.sqlite")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Week 05 Day 21 - RAG indexing pipeline")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Run indexing with one strategy")
    p_index.add_argument("--source", required=True, help="File or directory to index")
    p_index.add_argument("--strategy", choices=["fixed", "structure"], required=True)
    p_index.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    p_index.add_argument("--dry-run", action="store_true", default=False)
    p_index.add_argument("--limit", type=int, default=None)

    p_compare = sub.add_parser("compare", help="Run both strategies and compare")
    p_compare.add_argument("--source", required=True, help="File or directory to index")
    p_compare.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    p_compare.add_argument("--dry-run", action="store_true", default=False)
    p_compare.add_argument("--limit", type=int, default=None)

    sub.add_parser("stats", help="Print overall DB stats")
    return parser.parse_args()


def _print_index_result(out: PipelineOutput) -> None:
    approx_tokens = max(1, out.result.approx_chars // 4) if out.result.approx_chars else 0
    print(f"\n[{out.result.strategy}] run_id={out.result.run_id}")
    print(f"source: {out.result.source_root}")
    print(f"db: {out.result.db_path}")
    print(
        f"documents={out.result.document_count} chunks={out.result.chunk_count} "
        f"missing_embeddings={out.result.missing_embedding_count}"
    )
    print(
        f"cache_hits={out.result.cache_hits} api_calls={out.result.api_calls} "
        f"avg_chunk_chars={out.result.avg_chunk_chars:.1f}"
    )
    print(
        f"chunk_stats: min={out.stats.min_chunk_chars} max={out.stats.max_chunk_chars} "
        f"sources={out.stats.source_count}"
    )
    print(f"estimated_volume: chars={out.result.approx_chars} approx_tokens={approx_tokens}")
    if out.warnings:
        print("warnings:")
        for warn in out.warnings[:8]:
            print(f"  - {warn}")
        if len(out.warnings) > 8:
            print(f"  - ... {len(out.warnings) - 8} more warnings")


def _print_strategy_report(store: IndexStore, run_id: str, label: str) -> None:
    rows = store.run_chunks(run_id)
    lengths = [len(str(row["text"])) for row in rows]
    per_source = store.chunks_per_source(run_id)
    if lengths:
        mn = min(lengths)
        mx = max(lengths)
        avg = sum(lengths) / len(lengths)
    else:
        mn = 0
        mx = 0
        avg = 0.0
    print(f"\n{label}:")
    print(f"  chunks={len(rows)} avg/min/max chars={avg:.1f}/{mn}/{mx}")
    print(f"  sources={len(per_source)}")
    top_sources = sorted(per_source.items(), key=lambda p: (-p[1], p[0]))[:5]
    for source, count in top_sources:
        print(f"    - {source}: {count}")

    print("  samples:")
    sample_rows = rows[:3]
    for row in sample_rows:
        text = str(row["text"]).replace("\n", " ").strip()
        preview = text[:120] + ("..." if len(text) > 120 else "")
        print(f"    - section={row['section']} source={row['source']} text='{preview}'")


def _command_index(args: argparse.Namespace) -> None:
    source = Path(args.source)
    db = Path(args.db)
    print(
        f"Indexing source={source} strategy={args.strategy} dry_run={args.dry_run} "
        f"limit={args.limit}"
    )
    output = index_documents(
        source=source,
        strategy=args.strategy,
        db_path=db,
        embedding_model=args.model,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    _print_index_result(output)


def _command_compare(args: argparse.Namespace) -> None:
    source = Path(args.source)
    db = Path(args.db)
    print(
        f"Comparing strategies for source={source} dry_run={args.dry_run} limit={args.limit}\n"
    )
    fixed = index_documents(
        source=source,
        strategy="fixed",
        db_path=db,
        embedding_model=args.model,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    structure = index_documents(
        source=source,
        strategy="structure",
        db_path=db,
        embedding_model=args.model,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    _print_index_result(fixed)
    _print_index_result(structure)

    print("\n=== Strategy comparison ===")
    print(
        "fixed: predictable chunk windows, can split through section boundaries. "
        "structure: semantically aligned sections, but chunk sizes are less uniform."
    )
    if args.dry_run:
        print(
            "dry-run note: no rows were persisted to chunks table, so sample extraction "
            "from SQLite is skipped."
        )
        return

    store = IndexStore(db.resolve())
    store.init()
    _print_strategy_report(store, fixed.result.run_id, "fixed")
    _print_strategy_report(store, structure.result.run_id, "structure")
    print(
        "\ncache insight: compare cache_hits/api_calls above. Repeated text across strategies "
        "is not guaranteed to be high because each strategy can produce different chunk text."
    )


def _command_stats(args: argparse.Namespace) -> None:
    db = Path(args.db)
    store = IndexStore(db.resolve())
    store.init()
    stats = store.stats()
    print(json.dumps({"db": str(db.resolve()), **stats}, ensure_ascii=False, indent=2))


def run() -> None:
    args = _parse_args()
    if args.command == "index":
        _command_index(args)
    elif args.command == "compare":
        _command_compare(args)
    elif args.command == "stats":
        _command_stats(args)
