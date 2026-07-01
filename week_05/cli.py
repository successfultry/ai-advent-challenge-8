from __future__ import annotations

import argparse
import json
from pathlib import Path

from week_05.embeddings import DEFAULT_EMBEDDING_MODEL
from week_05.eval import run_eval
from week_05.index_store import IndexStore
from week_05.indexer import PipelineOutput, index_documents
from week_05.rag_qa import answer_plain, answer_rag

DEFAULT_DB_PATH = Path("data/week_05/rag_index.sqlite")


def _display_path(value: str | Path) -> str:
    path = Path(value)
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(value)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Week 05 - indexing + first RAG query")
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

    p_ask = sub.add_parser("ask", help="Ask in plain/rag/both modes")
    p_ask.add_argument(
        "--question",
        default=None,
        help="Question to answer; omit to enter interactive mode",
    )
    p_ask.add_argument("--mode", choices=["plain", "rag", "both"], default="both")
    p_ask.add_argument("--provider", default="GPT-4o mini")
    p_ask.add_argument("--source", default="week_05/corpus")
    p_ask.add_argument("--strategy", choices=["fixed", "structure"], default="structure")
    p_ask.add_argument("--top-k", type=int, default=5)
    p_ask.add_argument("--temperature", type=float, default=0.2)
    p_ask.add_argument("--max-tokens", type=int, default=500)

    p_eval = sub.add_parser("eval", help="Run 10-question plain vs rag evaluation")
    p_eval.add_argument("--dataset", default="week_05/eval/questions.json")
    p_eval.add_argument("--output", default="week_05/eval/results.json")
    p_eval.add_argument("--provider", default="GPT-4o mini")
    p_eval.add_argument("--source", default="week_05/corpus")
    p_eval.add_argument("--strategy", choices=["fixed", "structure"], default="structure")
    p_eval.add_argument("--top-k", type=int, default=5)
    p_eval.add_argument("--limit", type=int, default=None)
    p_eval.add_argument("--temperature", type=float, default=0.2)
    p_eval.add_argument("--max-tokens", type=int, default=500)
    return parser.parse_args()


def _usage_to_dict(usage: object | None) -> dict[str, int]:
    if usage is None:
        return {}
    if isinstance(usage, dict):
        raw = usage
    elif hasattr(usage, "model_dump"):
        raw = usage.model_dump()  # type: ignore[assignment]
    else:
        raw = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
    payload: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = raw.get(key)
        if isinstance(value, int):
            payload[key] = value
    return payload


def _print_index_result(out: PipelineOutput) -> None:
    approx_tokens = max(1, out.result.approx_chars // 4) if out.result.approx_chars else 0
    print(f"\n[{out.result.strategy}] run_id={out.result.run_id}")
    print(f"source: {_display_path(out.result.source_root)}")
    print(f"db: {_display_path(out.result.db_path)}")
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
        print(f"    - {_display_path(source)}: {count}")

    print("  samples:")
    sample_rows = rows[:3]
    for row in sample_rows:
        text = str(row["text"]).replace("\n", " ").strip()
        preview = text[:120] + ("..." if len(text) > 120 else "")
        source = _display_path(row["source"])
        print(f"    - section={row['section']} source={source} text='{preview}'")


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
    print(json.dumps({"db": _display_path(db), **stats}, ensure_ascii=False, indent=2))


def _print_answer_block(
    label: str,
    answer: str,
    usage: object | None,
    latency_s: float,
    model: str,
) -> None:
    usage_payload = _usage_to_dict(usage)
    print(f"\n[{label}] model={model} latency_s={latency_s:.2f}")
    if usage_payload:
        print(f"usage={json.dumps(usage_payload, ensure_ascii=False)}")
    print(answer)


def _answer_once(args: argparse.Namespace, question: str) -> None:
    source = Path(args.source)
    db = Path(args.db)
    mode = args.mode
    if mode in {"plain", "both"}:
        plain = answer_plain(
            question,
            args.provider,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        _print_answer_block("plain", plain.answer, plain.usage, plain.latency_s, plain.model)

    if mode in {"rag", "both"}:
        rag = answer_rag(
            question,
            args.provider,
            db,
            source,
            strategy=args.strategy,
            top_k=args.top_k,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        _print_answer_block("rag", rag.answer, rag.usage, rag.latency_s, rag.model)
        print(
            "retrieval: "
            f"run_id={rag.retrieval_run_id} model={rag.retrieval_embedding_model} "
            f"retrieved={rag.retrieved_count} avg_score={rag.avg_retrieval_score:.4f}"
        )
        if rag.citations:
            print("citations:")
            for citation in rag.citations:
                print(
                    "  - "
                    f"{citation.chunk_id} source={_display_path(citation.source)} "
                    f"section={citation.section} score={citation.score:.4f}"
                )
        else:
            print("citations: none")


def _command_ask(args: argparse.Namespace) -> None:
    source = Path(args.source)
    print(
        f"Ask mode={args.mode} provider={args.provider} strategy={args.strategy} "
        f"top_k={args.top_k} source={_display_path(source)}"
    )

    if args.question is not None and str(args.question).strip():
        _answer_once(args, str(args.question).strip())
        return

    print("Interactive mode. Type a question, empty line or 'exit'/'quit' to stop.")
    while True:
        try:
            question = input("\nquestion> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question or question.lower() in {"exit", "quit"}:
            break
        _answer_once(args, question)


def _command_eval(args: argparse.Namespace) -> None:
    db = Path(args.db)
    source = Path(args.source)
    dataset = Path(args.dataset)
    output = Path(args.output)
    report = run_eval(
        dataset_path=dataset,
        output_path=output,
        provider_name=args.provider,
        db_path=db,
        source_root=source,
        strategy=args.strategy,
        top_k=args.top_k,
        limit=args.limit,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    print(
        f"Eval provider={report.provider} strategy={report.strategy} "
        f"questions={report.summary.questions_run}/{report.summary.questions_total}"
    )
    print(
        "summary: "
        f"plain_kw={report.summary.avg_keyword_recall_plain:.3f} "
        f"rag_kw={report.summary.avg_keyword_recall_rag:.3f} "
        f"rag_source_hit={report.summary.rag_source_hit_rate:.3f}"
    )
    print("per-question:")
    for item in report.results:
        print(
            "  - "
            f"{item.id}: plain={item.keyword_recall_plain:.2f} "
            f"rag={item.keyword_recall_rag:.2f} source_hit={item.source_hit} "
            f"retrieved={item.retrieved_count}"
        )
    print(f"report: {_display_path(output)}")


def run() -> None:
    args = _parse_args()
    if args.command == "index":
        _command_index(args)
    elif args.command == "compare":
        _command_compare(args)
    elif args.command == "stats":
        _command_stats(args)
    elif args.command == "ask":
        _command_ask(args)
    elif args.command == "eval":
        _command_eval(args)
