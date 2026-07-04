from __future__ import annotations

import argparse
import json
from pathlib import Path

from week_05.agent import run_agent
from week_05.chat.runner import run_chat_turn
from week_05.chat.scenarios import run_chat_scenario
from week_05.chat.state import render_task_state
from week_05.embeddings import DEFAULT_EMBEDDING_MODEL
from week_05.eval import EvalProfileConfig, run_eval, run_eval_comparison
from week_05.index_store import IndexStore
from week_05.indexer import PipelineOutput, index_documents

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
    p_ask.add_argument("--top-k-before", type=int, default=None)
    p_ask.add_argument("--min-similarity", type=float, default=-1.0)
    p_ask.add_argument("--use-mmr", action="store_true", default=False)
    p_ask.add_argument("--rewrite-query", action="store_true", default=False)
    p_ask.add_argument("--hallucination-threshold", type=float, default=0.33)
    p_ask.add_argument("--min-grounded-chunks", type=int, default=1)
    p_ask.add_argument("--max-quotes", type=int, default=2)
    p_ask.add_argument("--quote-max-chars", type=int, default=200)
    p_ask.add_argument("--compact", action="store_true", default=False)
    p_ask.add_argument("--temperature", type=float, default=0.2)
    p_ask.add_argument("--max-tokens", type=int, default=500)

    p_eval = sub.add_parser("eval", help="Run 10-question plain vs rag evaluation")
    p_eval.add_argument("--dataset", default="week_05/eval/questions.json")
    p_eval.add_argument("--output", default="week_05/eval/results.json")
    p_eval.add_argument("--provider", default="GPT-4o mini")
    p_eval.add_argument("--source", default="week_05/corpus")
    p_eval.add_argument("--strategy", choices=["fixed", "structure"], default="structure")
    p_eval.add_argument("--top-k", type=int, default=5)
    p_eval.add_argument("--top-k-before", type=int, default=None)
    p_eval.add_argument("--min-similarity", type=float, default=-1.0)
    p_eval.add_argument("--use-mmr", action="store_true", default=False)
    p_eval.add_argument("--rewrite-query", action="store_true", default=False)
    p_eval.add_argument("--hallucination-threshold", type=float, default=0.33)
    p_eval.add_argument("--min-grounded-chunks", type=int, default=1)
    p_eval.add_argument("--max-quotes", type=int, default=2)
    p_eval.add_argument("--quote-max-chars", type=int, default=200)
    p_eval.add_argument("--compare", action="store_true", default=False)
    p_eval.add_argument("--limit", type=int, default=None)
    p_eval.add_argument("--temperature", type=float, default=0.2)
    p_eval.add_argument("--max-tokens", type=int, default=500)

    p_chat = sub.add_parser("chat", help="Run production-like mini-chat with RAG")
    p_chat.add_argument("--session-id", default=None)
    p_chat.add_argument("--provider", default="GPT-4o mini")
    p_chat.add_argument("--source", default="week_05/corpus")
    p_chat.add_argument("--strategy", choices=["fixed", "structure"], default="structure")
    p_chat.add_argument("--top-k", type=int, default=5)
    p_chat.add_argument("--top-k-before", type=int, default=20)
    p_chat.add_argument("--min-similarity", type=float, default=0.2)
    p_chat.add_argument("--use-mmr", action="store_true", default=False)
    p_chat.add_argument("--rewrite-query", action="store_true", default=False)
    p_chat.add_argument("--hallucination-threshold", type=float, default=0.33)
    p_chat.add_argument("--min-grounded-chunks", type=int, default=1)
    p_chat.add_argument("--max-quotes", type=int, default=2)
    p_chat.add_argument("--quote-max-chars", type=int, default=200)
    p_chat.add_argument("--history-limit", type=int, default=6)
    p_chat.add_argument("--show-state", action="store_true", default=False)
    p_chat.add_argument("--temperature", type=float, default=0.2)
    p_chat.add_argument("--max-tokens", type=int, default=500)

    p_chat_eval = sub.add_parser("chat-eval", help="Replay long chat scenario")
    p_chat_eval.add_argument("--scenario", required=True)
    p_chat_eval.add_argument("--provider", default="GPT-4o mini")
    p_chat_eval.add_argument("--source", default="week_05/corpus")
    p_chat_eval.add_argument("--strategy", choices=["fixed", "structure"], default="structure")
    p_chat_eval.add_argument("--top-k", type=int, default=5)
    p_chat_eval.add_argument("--top-k-before", type=int, default=20)
    p_chat_eval.add_argument("--min-similarity", type=float, default=0.2)
    p_chat_eval.add_argument("--use-mmr", action="store_true", default=False)
    p_chat_eval.add_argument("--rewrite-query", action="store_true", default=False)
    p_chat_eval.add_argument("--hallucination-threshold", type=float, default=0.33)
    p_chat_eval.add_argument("--min-grounded-chunks", type=int, default=1)
    p_chat_eval.add_argument("--max-quotes", type=int, default=2)
    p_chat_eval.add_argument("--quote-max-chars", type=int, default=200)
    p_chat_eval.add_argument("--history-limit", type=int, default=6)
    p_chat_eval.add_argument("--temperature", type=float, default=0.2)
    p_chat_eval.add_argument("--max-tokens", type=int, default=500)
    p_chat_eval.add_argument("--output", default=None)
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


def _print_rag_block(args: argparse.Namespace, rag: object) -> None:
    usage_payload = _usage_to_dict(rag.usage)
    print("\n=== RAG Answer ===")
    print(f"model={rag.model} latency_s={rag.latency_s:.2f}")
    if usage_payload:
        print(f"usage={json.dumps(usage_payload, ensure_ascii=False)}")
    print("\nAnswer:")
    print(rag.answer)

    used_labels = getattr(rag, "used_labels", []) or []
    print("\nUsed by answer:")
    print(f"  {', '.join(used_labels) if used_labels else 'none cited by model'}")

    print("\nRetrieved context:")
    if rag.citations:
        for idx, citation in enumerate(rag.citations, start=1):
            label = getattr(citation, "label", f"C{idx}") or f"C{idx}"
            used_mark = " *used" if getattr(citation, "used", False) else ""
            print(
                "  - "
                f"[{label}]{used_mark} path={_display_path(citation.source)} "
                f"section={citation.section} "
                f"chunk_id={citation.chunk_id} score={citation.score:.4f}"
            )
    else:
        print("  - none")

    if not args.compact:
        print("\nEvidence (used by answer):")
        if rag.quotes:
            for idx, quote in enumerate(rag.quotes, start=1):
                label = getattr(quote, "label", f"C{idx}") or f"C{idx}"
                display_text = " ".join(quote.text.split())
                print(f'  - [{label}] "{display_text}"')
        else:
            print("  - none")

    print("\nGrounding:")
    print(f"  grounded={rag.grounded} fallback_reason={rag.fallback_reason}")

    print("\nRetrieval:")
    print(
        "  "
        f"run_id={rag.retrieval_run_id} model={rag.retrieval_embedding_model} "
        f"before={rag.retrieved_before} after_threshold={rag.retrieved_after_threshold} "
        f"final={rag.retrieved_count} avg_score={rag.avg_retrieval_score:.4f}"
    )
    if rag.rewritten_query is not None:
        print(f"\nrewritten_query: {rag.rewritten_query}")


def _ask_settings_line(args: argparse.Namespace, source: Path) -> str:
    return (
        f"Ask mode={args.mode} provider={args.provider} strategy={args.strategy} "
        f"top_k={args.top_k} top_k_before={args.top_k_before} "
        f"min_similarity={args.min_similarity} mmr={args.use_mmr} "
        f"rewrite={args.rewrite_query} hall_threshold={args.hallucination_threshold} "
        f"min_grounded_chunks={args.min_grounded_chunks} max_quotes={args.max_quotes} "
        f"quote_max_chars={args.quote_max_chars} compact={args.compact} "
        f"source={_display_path(source)}"
    )


def _print_interactive_help() -> None:
    print(
        "\nInteractive commands:\n"
        "  :help                      show this help\n"
        "  :show                      show current settings\n"
        "  :provider <name>           set generation provider\n"
        "  :strategy fixed|structure  switch retrieval strategy\n"
        "  :mode plain|rag|both       switch answer mode\n"
        "  :top-k <int>               set final top-k chunks\n"
        "  :top-k-before <int|none>   set recall stage size\n"
        "  :min-similarity <float>    set threshold (e.g. 0.35)\n"
        "  :hall-threshold <float>    set anti-hallucination threshold\n"
        "  :min-grounded-chunks <int> set min chunks before grounded answer\n"
        "  :max-quotes <int>          set max quotes to print\n"
        "  :quote-max-chars <int>     set quote text cap\n"
        "  :compact on|off            hide/show quotes block\n"
        "  :mmr on|off                toggle MMR diversity\n"
        "  :rewrite on|off            toggle query rewrite\n"
        "  :reset                     reset settings to session defaults\n"
        "  exit / quit / empty line   stop interactive mode\n"
    )


def _parse_bool_toggle(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in {"on", "true", "1", "yes", "y"}:
        return True
    if normalized in {"off", "false", "0", "no", "n"}:
        return False
    raise ValueError("Expected on/off.")


def _apply_interactive_command(
    args: argparse.Namespace,
    original: dict[str, object],
    source: Path,
    command_line: str,
) -> bool:
    payload = command_line[1:].strip()
    if not payload:
        _print_interactive_help()
        return True

    parts = payload.split(maxsplit=1)
    command = parts[0].lower()
    value = parts[1].strip() if len(parts) > 1 else ""

    if command == "help":
        _print_interactive_help()
        return True
    if command == "show":
        print(_ask_settings_line(args, source))
        return True
    if command == "reset":
        args.provider = str(original["provider"])
        args.strategy = str(original["strategy"])
        args.mode = str(original["mode"])
        args.top_k = int(original["top_k"])
        args.top_k_before = (
            int(original["top_k_before"]) if original["top_k_before"] is not None else None
        )
        args.min_similarity = float(original["min_similarity"])
        args.use_mmr = bool(original["use_mmr"])
        args.rewrite_query = bool(original["rewrite_query"])
        args.hallucination_threshold = float(original["hallucination_threshold"])
        args.min_grounded_chunks = int(original["min_grounded_chunks"])
        args.max_quotes = int(original["max_quotes"])
        args.quote_max_chars = int(original["quote_max_chars"])
        args.compact = bool(original["compact"])
        print(f"Settings reset. {_ask_settings_line(args, source)}")
        return True

    try:
        if command == "provider":
            if not value:
                raise ValueError("Expected provider name.")
            args.provider = value
        elif command == "strategy":
            if value not in {"fixed", "structure"}:
                raise ValueError("Expected fixed|structure.")
            args.strategy = value
        elif command == "mode":
            if value not in {"plain", "rag", "both"}:
                raise ValueError("Expected plain|rag|both.")
            args.mode = value
        elif command == "top-k":
            parsed = int(value)
            if parsed < 0:
                raise ValueError("top-k must be >= 0.")
            args.top_k = parsed
        elif command == "top-k-before":
            if value.lower() == "none":
                args.top_k_before = None
            else:
                parsed = int(value)
                if parsed < 0:
                    raise ValueError("top-k-before must be >= 0 or none.")
                args.top_k_before = parsed
        elif command == "min-similarity":
            args.min_similarity = float(value)
        elif command == "hall-threshold":
            args.hallucination_threshold = float(value)
        elif command == "min-grounded-chunks":
            parsed = int(value)
            if parsed < 1:
                raise ValueError("min-grounded-chunks must be >= 1.")
            args.min_grounded_chunks = parsed
        elif command == "max-quotes":
            parsed = int(value)
            if parsed < 0:
                raise ValueError("max-quotes must be >= 0.")
            args.max_quotes = parsed
        elif command == "quote-max-chars":
            parsed = int(value)
            if parsed < 1:
                raise ValueError("quote-max-chars must be >= 1.")
            args.quote_max_chars = parsed
        elif command == "compact":
            args.compact = _parse_bool_toggle(value)
        elif command == "mmr":
            args.use_mmr = _parse_bool_toggle(value)
        elif command == "rewrite":
            args.rewrite_query = _parse_bool_toggle(value)
        else:
            print(f"Unknown command: {command_line}")
            _print_interactive_help()
            return True
    except (TypeError, ValueError) as exc:
        print(f"Invalid command value: {exc}")
        return True

    print(f"Updated. {_ask_settings_line(args, source)}")
    return True


def _answer_once(args: argparse.Namespace, question: str) -> None:
    source = Path(args.source)
    db = Path(args.db)
    result = run_agent(
        question,
        mode=args.mode,
        provider_name=args.provider,
        db_path=db,
        source_root=source,
        strategy=args.strategy,
        top_k=args.top_k,
        top_k_before=args.top_k_before,
        min_similarity=args.min_similarity,
        use_mmr=args.use_mmr,
        rewrite_query=args.rewrite_query,
        hallucination_threshold=args.hallucination_threshold,
        min_grounded_chunks=args.min_grounded_chunks,
        max_quotes=args.max_quotes,
        quote_max_chars=args.quote_max_chars,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    if result.plain is not None:
        plain = result.plain
        _print_answer_block("plain", plain.answer, plain.usage, plain.latency_s, plain.model)

    if result.rag is not None:
        rag = result.rag
        _print_rag_block(args, rag)


def _command_ask(args: argparse.Namespace) -> None:
    source = Path(args.source)
    print(_ask_settings_line(args, source))

    if args.question is not None and str(args.question).strip():
        _answer_once(args, str(args.question).strip())
        return

    print("Interactive mode. Type :help for commands.")
    print("Type a question, empty line or 'exit'/'quit' to stop.")
    original = {
        "provider": args.provider,
        "strategy": args.strategy,
        "mode": args.mode,
        "top_k": args.top_k,
        "top_k_before": args.top_k_before,
        "min_similarity": args.min_similarity,
        "use_mmr": args.use_mmr,
        "rewrite_query": args.rewrite_query,
        "hallucination_threshold": args.hallucination_threshold,
        "min_grounded_chunks": args.min_grounded_chunks,
        "max_quotes": args.max_quotes,
        "quote_max_chars": args.quote_max_chars,
        "compact": args.compact,
    }
    while True:
        try:
            question = input("\nquestion> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question or question.lower() in {"exit", "quit"}:
            break
        if question.startswith(":"):
            _apply_interactive_command(args, original, source, question)
            continue
        _answer_once(args, question)


def _command_eval(args: argparse.Namespace) -> None:
    db = Path(args.db)
    source = Path(args.source)
    dataset = Path(args.dataset)
    output = Path(args.output)
    if args.compare:
        improved_rewrite = args.rewrite_query
        improved_mmr = args.use_mmr
        if not improved_rewrite and not improved_mmr:
            improved_rewrite = True
            improved_mmr = True
        profiles = [
            EvalProfileConfig(name="baseline", top_k=args.top_k),
            EvalProfileConfig(
                name="improved",
                top_k=args.top_k,
                top_k_before=args.top_k_before if args.top_k_before is not None else 20,
                min_similarity=args.min_similarity if args.min_similarity > -1.0 else 0.35,
                use_mmr=improved_mmr,
                rewrite_query=improved_rewrite,
                hallucination_threshold=args.hallucination_threshold,
                min_grounded_chunks=args.min_grounded_chunks,
                max_quotes=args.max_quotes,
                quote_max_chars=args.quote_max_chars,
            ),
        ]
        comparison = run_eval_comparison(
            dataset_path=dataset,
            output_path=output,
            provider_name=args.provider,
            db_path=db,
            source_root=source,
            strategy=args.strategy,
            profiles=profiles,
            limit=args.limit,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        print(
            f"Eval compare provider={comparison.provider} strategy={comparison.strategy} "
            f"profiles={len(comparison.profiles)}"
        )
        print("profile summary:")
        for profile in comparison.profiles:
            print(
                "  - "
                f"{profile.profile}: plain_kw={profile.avg_keyword_recall_plain:.3f} "
                f"rag_kw={profile.avg_keyword_recall_rag:.3f} "
                f"source_hit={profile.source_hit_rate:.3f} "
                f"sources={profile.answers_with_sources_rate:.3f} "
                f"quotes={profile.answers_with_quotes_rate:.3f} "
                f"quote_kw_overlap={profile.avg_quote_keyword_overlap:.3f} "
                f"fallback_rate={profile.fallback_rate:.3f} "
                f"avg_retrieved_final={profile.avg_retrieved_final:.2f}"
            )
        print(f"report: {_display_path(output)}")
        return

    report = run_eval(
        dataset_path=dataset,
        output_path=output,
        provider_name=args.provider,
        db_path=db,
        source_root=source,
        strategy=args.strategy,
        top_k=args.top_k,
        top_k_before=args.top_k_before,
        min_similarity=args.min_similarity,
        use_mmr=args.use_mmr,
        rewrite_query=args.rewrite_query,
        hallucination_threshold=args.hallucination_threshold,
        min_grounded_chunks=args.min_grounded_chunks,
        max_quotes=args.max_quotes,
        quote_max_chars=args.quote_max_chars,
        limit=args.limit,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    print(
        f"Eval provider={report.provider} strategy={report.strategy} "
        "profile="
        f"{report.profile} "
        f"questions={report.summary.questions_run}/{report.summary.questions_total}"
    )
    print(
        "summary: "
        f"plain_kw={report.summary.avg_keyword_recall_plain:.3f} "
        f"rag_kw={report.summary.avg_keyword_recall_rag:.3f} "
        f"rag_source_hit={report.summary.rag_source_hit_rate:.3f} "
        f"sources={report.summary.answers_with_sources_rate:.3f} "
        f"quotes={report.summary.answers_with_quotes_rate:.3f} "
        f"quote_kw_overlap={report.summary.avg_quote_keyword_overlap:.3f} "
        f"fallback_rate={report.summary.fallback_rate:.3f}"
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


def _chat_sessions_dir() -> Path:
    return Path("data/week_05/chat_sessions")


def _print_chat_turn(result: object, *, show_state: bool) -> None:
    session = result.session
    answer = result.answer
    print(
        f"\nsession_id={session.session_id} saved_to="
        f"{_display_path(result.session_path)}"
    )
    print("\nAnswer:")
    print(answer.answer)
    used_labels = getattr(answer, "used_labels", []) or []
    print("\nUsed by answer:")
    print(f"  {', '.join(used_labels) if used_labels else 'none cited by model'}")
    print("\nSources (retrieved candidates, * = used by model):")
    if answer.citations:
        for idx, citation in enumerate(answer.citations, start=1):
            label = getattr(citation, "label", "") or f"C{idx}"
            used_mark = " *" if getattr(citation, "used", False) else ""
            print(
                f"  - [{label}]{used_mark} chunk_id={citation.chunk_id} "
                f"path={_display_path(citation.source)} "
                f"section={citation.section} score={citation.score:.4f}"
            )
    else:
        print("  - none")
    print("\nGrounding:")
    print(f"  grounded={answer.grounded} fallback_reason={answer.fallback_reason}")
    print("\nRetrieval:")
    print(
        "  "
        f"run_id={answer.retrieval_run_id} model={answer.retrieval_embedding_model} "
        f"before={answer.retrieved_before} after_threshold={answer.retrieved_after_threshold} "
        f"final={answer.retrieved_count} avg_score={answer.avg_retrieval_score:.4f}"
    )
    if show_state:
        print("\nTask state:")
        print(f"  {render_task_state(session.task_state)}")


def _command_chat(args: argparse.Namespace) -> None:
    source = Path(args.source)
    db = Path(args.db)
    sessions_dir = _chat_sessions_dir()
    print("Chat mode. Type :help for commands.")
    print("Type a message, empty line or 'exit'/'quit' to stop.")
    print(f"session_id={args.session_id or '(new auto-generated)'}")
    while True:
        try:
            raw = input("\nchat> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw or raw.lower() in {"exit", "quit", ":exit"}:
            break
        if raw == ":help":
            print(
                "\nChat commands:\n"
                "  :help      show help\n"
                "  :state     show task state\n"
                "  :history   show last turns\n"
                "  :save      save session snapshot now\n"
                "  :exit      quit\n"
            )
            continue
        if raw in {":state", ":history", ":save"} and args.session_id is None:
            print("No session yet. Send first user message to create it.")
            continue
        if raw in {":state", ":history", ":save"} and args.session_id is not None:
            session_path = sessions_dir / f"{args.session_id}.json"
            if not session_path.exists():
                print("Session file not found yet.")
                continue
            from week_05.chat.session import load_session, save_session

            session = load_session(session_path)
            if raw == ":state":
                print(render_task_state(session.task_state))
            elif raw == ":history":
                print(f"turns={len(session.turns)}")
                for turn in session.turns[-6:]:
                    print(f"  - {turn.role}: {turn.text[:120]}")
            else:
                save_session(session_path, session)
                print(f"saved_to={_display_path(session_path)}")
            continue
        if raw.startswith(":"):
            print(f"Unknown command: {raw}")
            continue

        result = run_chat_turn(
            user_message=raw,
            provider_name=args.provider,
            db_path=db,
            source_root=source,
            sessions_dir=sessions_dir,
            session_id=args.session_id,
            strategy=args.strategy,
            top_k=args.top_k,
            top_k_before=args.top_k_before,
            min_similarity=args.min_similarity,
            use_mmr=args.use_mmr,
            rewrite_query=args.rewrite_query,
            hallucination_threshold=args.hallucination_threshold,
            min_grounded_chunks=args.min_grounded_chunks,
            max_quotes=args.max_quotes,
            quote_max_chars=args.quote_max_chars,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            history_limit=args.history_limit,
        )
        args.session_id = result.session.session_id
        _print_chat_turn(result, show_state=args.show_state)


def _command_chat_eval(args: argparse.Namespace) -> None:
    source = Path(args.source)
    db = Path(args.db)
    report = run_chat_scenario(
        scenario_path=Path(args.scenario),
        provider_name=args.provider,
        db_path=db,
        source_root=source,
        sessions_dir=_chat_sessions_dir(),
        strategy=args.strategy,
        top_k=args.top_k,
        top_k_before=args.top_k_before,
        min_similarity=args.min_similarity,
        use_mmr=args.use_mmr,
        rewrite_query=args.rewrite_query,
        hallucination_threshold=args.hallucination_threshold,
        min_grounded_chunks=args.min_grounded_chunks,
        max_quotes=args.max_quotes,
        quote_max_chars=args.quote_max_chars,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        history_limit=args.history_limit,
    )
    payload = {
        "scenario_id": report.scenario_id,
        "turns_total": report.turns_total,
        "source_presence_rate": report.source_presence_rate,
        "grounded_source_rate": report.grounded_source_rate,
        "fallback_count": report.fallback_count,
        "goal_retention_rate": report.goal_retention_rate,
        "session_path": report.session_path,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.output is not None:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
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
    elif args.command == "chat":
        _command_chat(args)
    elif args.command == "chat-eval":
        _command_chat_eval(args)
